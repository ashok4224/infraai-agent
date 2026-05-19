"""Chat tool registry — build Azure AI Foundry function schemas for live diagnostics.

This module provides tool definitions that can be passed to Azure AI Foundry
agents so they can request live diagnostics via function calling.

The backend handles validation, approval, and execution — the Azure agent
only reasons about WHAT to check, not HOW to execute.
"""
from __future__ import annotations

import logging
from typing import Dict, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mcp_config import MCPServerConfig
from app.models.server_config import ServerConfig

logger = logging.getLogger(__name__)


def _unwrap_mcp_output(result) -> object:
    """Unwrap the MCP stdio content envelope.

    MCP servers wrap their responses as:
        {"content": [{"type": "text", "text": "<json_string>"}]}

    Extract the inner JSON and parse it. If the inner text is itself a
    JSON-encoded dict/list, return the parsed object. Otherwise return as-is.
    """
    import json as _json

    if not isinstance(result, dict):
        return result

    content = result.get("content")
    if not isinstance(content, list) or not content:
        return result

    first = content[0]
    if not isinstance(first, dict) or first.get("type") != "text":
        return result

    text = first.get("text", "")
    if not isinstance(text, str):
        return result

    try:
        parsed = _json.loads(text)
        # Strip ResponseMetadata from AWS responses
        if isinstance(parsed, dict):
            parsed.pop("ResponseMetadata", None)
            # If the inner dict is itself a {"success":..., "data":...} wrapper, unwrap it
            if "data" in parsed and "success" in parsed:
                return parsed.get("data", parsed)
        return parsed
    except (_json.JSONDecodeError, ValueError):
        return text


def _sanitize_tool_name(name: str) -> str:
    """Convert server name to a valid OpenAI function name.

    Rules: a-z, A-Z, 0-9, underscore or hyphen, max 64 chars.
    """
    sanitized = "".join(c if c.isalnum() or c in "_-" else "_" for c in name)
    return sanitized[:64]


def _build_oracle_tool_schema(mcp: MCPServerConfig) -> dict:
    """Build function schema for an Oracle MCP server."""
    safe_name = _sanitize_tool_name(mcp.name)
    return {
        "type": "function",
        "function": {
            "name": f"query_oracle_{safe_name}",
            "description": (
                f"Run a read-only SQL query on Oracle database '{mcp.name}' "
                f"({mcp.oracle_host}:{mcp.oracle_port}/{mcp.oracle_service}). "
                f"Use SELECT, WITH, SHOW, DESCRIBE, or EXPLAIN only."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": (
                            "A read-only SQL query. Examples: "
                            "SELECT * FROM v$instance; "
                            "SELECT tablespace_name, bytes_used FROM dba_tablespace_usage_metrics;"
                        ),
                    }
                },
                "required": ["sql"],
                "additionalProperties": False,
            },
        },
    }


def _build_postgres_tool_schema(mcp: MCPServerConfig) -> dict:
    """Build function schema for a PostgreSQL MCP server."""
    safe_name = _sanitize_tool_name(mcp.name)
    return {
        "type": "function",
        "function": {
            "name": f"query_postgres_{safe_name}",
            "description": (
                f"Run a read-only SQL query on PostgreSQL database '{mcp.name}' "
                f"({mcp.oracle_host or 'unknown'}:{mcp.oracle_port or 5432}). "
                f"Use SELECT, WITH, SHOW, or EXPLAIN only."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": (
                            "A read-only SQL query. Examples: "
                            "SELECT count(*) FROM users; "
                            "SELECT * FROM pg_stat_activity;"
                        ),
                    }
                },
                "required": ["sql"],
                "additionalProperties": False,
            },
        },
    }


def _build_mysql_tool_schema(mcp: MCPServerConfig) -> dict:
    """Build function schema for a MySQL MCP server."""
    safe_name = _sanitize_tool_name(mcp.name)
    return {
        "type": "function",
        "function": {
            "name": f"query_mysql_{safe_name}",
            "description": (
                f"Run a read-only SQL query on MySQL database '{mcp.name}' "
                f"({mcp.oracle_host or 'unknown'}:{mcp.oracle_port or 3306}). "
                f"Use SELECT, SHOW, or EXPLAIN only."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sql": {
                        "type": "string",
                        "description": (
                            "A read-only SQL query. Examples: "
                            "SELECT count(*) FROM information_schema.tables; "
                            "SHOW PROCESSLIST;"
                        ),
                    }
                },
                "required": ["sql"],
                "additionalProperties": False,
            },
        },
    }


def _build_ssh_tool_schema(server: ServerConfig) -> dict:
    """Build function schema for an SSH server."""
    safe_name = _sanitize_tool_name(server.name)
    return {
        "type": "function",
        "function": {
            "name": f"run_ssh_{safe_name}",
            "description": (
                f"Run a safe read-only diagnostic command on Linux server '{server.name}' "
                f"({server.host}, OS={server.os_type or 'linux'}). "
                f"Allowed: df, du, free, uptime, ps, top, iostat, vmstat, ss, ip, "
                f"netstat, systemctl, journalctl, ls, cat, tail, head, grep, find, "
                f"kubectl get/describe/logs/top."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": (
                            "A safe shell command. Examples: "
                            "df -h; free -h; uptime; ps aux --sort=-%mem | head -15; "
                            "kubectl get nodes; kubectl get pods --all-namespaces"
                        ),
                    }
                },
                "required": ["command"],
                "additionalProperties": False,
            },
        },
    }


def _build_aws_tool_schema(mcp: MCPServerConfig) -> dict:
    """Build function schema for an AWS MCP server."""
    safe_name = _sanitize_tool_name(mcp.name)
    return {
        "type": "function",
        "function": {
            "name": f"call_aws_{safe_name}",
            "description": (
                f"Call AWS API via MCP server '{mcp.name}'. "
                f"Supports EC2, EKS, CloudWatch, RDS, and other AWS services. "
                f"IMPORTANT: Use 'region' (top-level, e.g. 'ap-south-1') for the AWS region — do NOT put region inside params. "
                f"Many operations also require params: "
                f"EKS list_clusters: params={{}}, region='ap-south-1'. "
                f"EKS list_nodegroups: params={{\"clusterName\": \"<name>\"}}, region='ap-south-1'. "
                f"EKS describe_cluster: params={{\"name\": \"<cluster-name>\"}}, region='ap-south-1'. "
                f"EC2 describe_instances: params={{\"Filters\": [...]}}, region='ap-south-1'. "
                f"Always set 'region' at the top level, never inside 'params'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {
                        "type": "string",
                        "description": "AWS service name, e.g. ec2, eks, cloudwatch, rds",
                        "enum": ["ec2", "eks", "cloudwatch", "rds", "lambda", "s3"],
                    },
                    "operation": {
                        "type": "string",
                        "description": (
                            "AWS API operation in snake_case, e.g. list_clusters, list_nodegroups, "
                            "describe_cluster, describe_instances, get_metric_statistics."
                        ),
                    },
                    "params": {
                        "type": "object",
                        "description": (
                            "API call parameters — do NOT include region here. "
                            "list_clusters: {} (empty). "
                            "list_nodegroups: {\"clusterName\": \"<name>\"}. "
                            "describe_cluster: {\"name\": \"<cluster-name>\"}.  "
                            "describe_nodegroup: {\"clusterName\": \"<name>\", \"nodegroupName\": \"<ng>\"}."
                        ),
                        "default": {},
                    },
                    "region": {
                        "type": "string",
                        "description": (
                            "AWS region code, e.g. ap-south-1, us-east-1, eu-west-1. "
                            "ALWAYS set this — do not put region inside params."
                        ),
                    },
                },
                "required": ["service", "operation", "region"],
                "additionalProperties": False,
            },
        },
    }


def _build_azure_tool_schema(mcp: MCPServerConfig) -> dict:
    """Build function schema for an Azure MCP server."""
    safe_name = _sanitize_tool_name(mcp.name)
    return {
        "type": "function",
        "function": {
            "name": f"call_azure_{safe_name}",
            "description": (
                f"Call Azure API via MCP server '{mcp.name}'. "
                f"Supports Compute, Monitor, and other Azure services."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "service": {
                        "type": "string",
                        "description": "Azure service name, e.g. compute, monitor",
                        "enum": ["compute", "monitor", "network", "storage"],
                    },
                    "operation": {
                        "type": "string",
                        "description": "Azure API operation, e.g. list_vms, list_metrics",
                    },
                    "params": {
                        "type": "object",
                        "description": "Optional parameters for the Azure API call",
                        "default": {},
                    },
                },
                "required": ["service", "operation"],
                "additionalProperties": False,
            },
        },
    }


def _build_kubernetes_tool_schema(mcp: MCPServerConfig) -> dict:
    """Build function schema for a Kubernetes MCP server."""
    safe_name = _sanitize_tool_name(mcp.name)
    return {
        "type": "function",
        "function": {
            "name": f"call_k8s_{safe_name}",
            "description": (
                f"Run kubectl commands via MCP server '{mcp.name}'. "
                f"Supports get, describe, logs, top operations."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "verb": {
                        "type": "string",
                        "description": "kubectl verb",
                        "enum": ["get", "describe", "logs", "top"],
                    },
                    "resource": {
                        "type": "string",
                        "description": "Kubernetes resource type, e.g. nodes, pods, services",
                    },
                    "namespace": {
                        "type": "string",
                        "description": "Namespace (optional, default: all)",
                        "default": "",
                    },
                    "extra_args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Extra arguments, e.g. ['--all-namespaces']",
                        "default": [],
                    },
                },
                "required": ["verb", "resource"],
                "additionalProperties": False,
            },
        },
    }


def _build_mongodb_tool_schema(mcp: MCPServerConfig) -> dict:
    """Build function schema for a MongoDB MCP server."""
    safe_name = _sanitize_tool_name(mcp.name)
    return {
        "type": "function",
        "function": {
            "name": f"query_mongodb_{safe_name}",
            "description": (
                f"Run a read-only diagnostic query on MongoDB server '{mcp.name}'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": (
                            "A MongoDB diagnostic command. Examples: "
                            "db.serverStatus(); db.currentOp(); rs.status();"
                        ),
                    }
                },
                "required": ["command"],
                "additionalProperties": False,
            },
        },
    }


def _mcp_to_tool_schema(mcp: MCPServerConfig) -> dict | None:
    """Build the appropriate tool schema for an MCP server based on its type."""
    mcp_type = (mcp.server_type or "").lower()

    if mcp_type in ("oracle", "oracle_db", "ora"):
        return _build_oracle_tool_schema(mcp)
    if mcp_type in ("postgresql", "postgres", "pg"):
        return _build_postgres_tool_schema(mcp)
    if mcp_type in ("mysql", "my"):
        return _build_mysql_tool_schema(mcp)
    if mcp_type == "aws":
        return _build_aws_tool_schema(mcp)
    if mcp_type == "azure":
        return _build_azure_tool_schema(mcp)
    if mcp_type in ("kubernetes", "k8s"):
        return _build_kubernetes_tool_schema(mcp)
    if mcp_type in ("mongodb", "mongo"):
        return _build_mongodb_tool_schema(mcp)

    logger.debug("No tool schema available for MCP type '%s' (server: %s)", mcp_type, mcp.name)
    return None


async def build_chat_tools(db: AsyncSession) -> list[dict]:
    """Build OpenAI function schemas for all active infrastructure tools.

    Returns a list of tool definitions that can be passed to
    Azure AI Foundry's function calling API.
    """
    tools: list[dict] = []

    # ── MCP servers (databases, cloud, k8s) ──
    mcp_result = await db.execute(
        select(MCPServerConfig).where(MCPServerConfig.is_active == True)
    )
    for mcp in mcp_result.scalars().all():
        schema = _mcp_to_tool_schema(mcp)
        if schema:
            tools.append(schema)

    # ── SSH servers (Linux OS diagnostics) ──
    ssh_result = await db.execute(
        select(ServerConfig).where(ServerConfig.is_active == True)
    )
    for server in ssh_result.scalars().all():
        tools.append(_build_ssh_tool_schema(server))

    logger.info("Built %d chat tools (%d MCP + %d SSH)",
                len(tools),
                len([t for t in tools if "query_" in t["function"]["name"] or "call_" in t["function"]["name"]]),
                len([t for t in tools if "run_ssh_" in t["function"]["name"]]))

    return tools


# ---------------------------------------------------------------------------
# Tool execution mapping — turn an Azure function call into a backend call
# ---------------------------------------------------------------------------

async def execute_chat_tool_call(db: AsyncSession, call: dict) -> dict:
    """Execute a single tool call requested by the Azure agent.

    Args:
        call: {"name": "query_oracle_prod", "arguments": {"sql": "SELECT ..."}}

    Returns:
        {"success": bool, "output": any, "error": str | None}
    """
    from app.services.safety import is_sql_safe, is_shell_command_safe
    from app.services.mcp_service import fetch_oracle_data, call_mcp_tool
    from app.services.ssh_service import run_ssh_command

    name = call.get("name", "")
    args = call.get("arguments", {})

    # ── Parse the tool name to determine server type ──
    if name.startswith("query_oracle_"):
        server_name = name[len("query_oracle_"):]
        sql = args.get("sql", "")

        # Safety check
        safety = is_sql_safe(sql)
        if not safety.get("allowed"):
            return {"success": False, "error": f"Blocked: {safety.get('reason')}", "output": None}

        # Find MCP config
        result = await db.execute(
            select(MCPServerConfig).where(
                MCPServerConfig.is_active == True,
                MCPServerConfig.name == server_name,
            )
        )
        mcp = result.scalar_one_or_none()
        if not mcp:
            return {"success": False, "error": f"Oracle MCP server '{server_name}' not found", "output": None}

        data = await fetch_oracle_data(mcp, sql)
        return {"success": data.get("success", False), "output": data.get("data"), "error": data.get("error")}

    elif name.startswith("query_postgres_"):
        server_name = name[len("query_postgres_"):]
        sql = args.get("sql", "")

        safety = is_sql_safe(sql)
        if not safety.get("allowed"):
            return {"success": False, "error": f"Blocked: {safety.get('reason')}", "output": None}

        result = await db.execute(
            select(MCPServerConfig).where(
                MCPServerConfig.is_active == True,
                MCPServerConfig.name == server_name,
            )
        )
        mcp = result.scalar_one_or_none()
        if not mcp:
            return {"success": False, "error": f"PostgreSQL MCP server '{server_name}' not found", "output": None}

        data = await fetch_oracle_data(mcp, sql)
        return {"success": data.get("success", False), "output": data.get("data"), "error": data.get("error")}

    elif name.startswith("query_mysql_"):
        server_name = name[len("query_mysql_"):]
        sql = args.get("sql", "")

        safety = is_sql_safe(sql)
        if not safety.get("allowed"):
            return {"success": False, "error": f"Blocked: {safety.get('reason')}", "output": None}

        result = await db.execute(
            select(MCPServerConfig).where(
                MCPServerConfig.is_active == True,
                MCPServerConfig.name == server_name,
            )
        )
        mcp = result.scalar_one_or_none()
        if not mcp:
            return {"success": False, "error": f"MySQL MCP server '{server_name}' not found", "output": None}

        data = await fetch_oracle_data(mcp, sql)
        return {"success": data.get("success", False), "output": data.get("data"), "error": data.get("error")}

    elif name.startswith("call_aws_"):
        server_name = name[len("call_aws_"):]
        service = args.get("service", "")
        operation = args.get("operation", "")
        params = dict(args.get("params") or {})
        # region must go to the client constructor, not the API call params
        region = args.get("region") or params.pop("region", None) or params.pop("Region", None)

        if not service or not operation:
            return {"success": False, "error": "AWS call requires 'service' and 'operation'", "output": None}

        # Try direct boto3 first (no MCP subprocess needed)
        try:
            import boto3
            import asyncio as _aio
            import json as _json
            from datetime import datetime, date

            def _boto3_call():
                kwargs = {}
                if region:
                    kwargs["region_name"] = region
                client = boto3.client(service, **kwargs)
                method = getattr(client, operation)
                resp = method(**params)
                resp.pop("ResponseMetadata", None)
                # Round-trip through JSON to convert datetime → str and make it serializable
                return _json.loads(_json.dumps(resp, default=str))

            data = await _aio.wait_for(_aio.to_thread(_boto3_call), timeout=30.0)
            return {"success": True, "output": data, "error": None}
        except ImportError:
            pass
        except Exception as boto_err:
            logger.warning("Direct boto3 call %s.%s failed: %s — trying MCP", service, operation, boto_err)

        # Fallback: MCP subprocess
        result = await db.execute(
            select(MCPServerConfig).where(
                MCPServerConfig.is_active == True,
                MCPServerConfig.name == server_name,
            )
        )
        mcp = result.scalar_one_or_none()
        if not mcp:
            return {"success": False, "error": f"AWS MCP server '{server_name}' not found and boto3 unavailable", "output": None}

        mcp_data = await call_mcp_tool(mcp, "aws_exec", {
            "service": service,
            "operation": operation,
            "params": params,
        })
        # Unwrap MCP content envelope: {"content": [{"type":"text","text":"json_string"}]}
        output = _unwrap_mcp_output(mcp_data.result)
        success = mcp_data.success and not (isinstance(output, dict) and output.get("error"))
        error = mcp_data.error or (output.get("error") if isinstance(output, dict) else None)
        return {"success": success, "output": output, "error": error}

    elif name.startswith("call_azure_"):
        server_name = name[len("call_azure_"):]
        service = args.get("service", "")
        operation = args.get("operation", "")
        params = args.get("params") or {}

        result = await db.execute(
            select(MCPServerConfig).where(
                MCPServerConfig.is_active == True,
                MCPServerConfig.name == server_name,
            )
        )
        mcp = result.scalar_one_or_none()
        if not mcp:
            return {"success": False, "error": f"Azure MCP server '{server_name}' not found", "output": None}

        mcp_data = await call_mcp_tool(mcp, "azure_exec", {
            "service": service,
            "operation": operation,
            "params": params,
        })
        output = _unwrap_mcp_output(mcp_data.result)
        return {"success": mcp_data.success, "output": output, "error": mcp_data.error}

    elif name.startswith("call_k8s_"):
        server_name = name[len("call_k8s_"):]
        verb = args.get("verb", "get")
        resource = args.get("resource", "pods")
        namespace = args.get("namespace", "")
        extra_args = args.get("extra_args") or []

        result = await db.execute(
            select(MCPServerConfig).where(
                MCPServerConfig.is_active == True,
                MCPServerConfig.name == server_name,
            )
        )
        mcp = result.scalar_one_or_none()
        if not mcp:
            return {"success": False, "error": f"K8s MCP server '{server_name}' not found", "output": None}

        mcp_data = await call_mcp_tool(mcp, "k8s_exec", {
            "verb": verb,
            "resource": resource,
            "namespace": namespace,
            "extra_args": extra_args,
        })
        output = _unwrap_mcp_output(mcp_data.result)
        return {"success": mcp_data.success, "output": output, "error": mcp_data.error}

    elif name.startswith("query_mongodb_"):
        server_name = name[len("query_mongodb_"):]
        command = args.get("command", "")

        result = await db.execute(
            select(MCPServerConfig).where(
                MCPServerConfig.is_active == True,
                MCPServerConfig.name == server_name,
            )
        )
        mcp = result.scalar_one_or_none()
        if not mcp:
            return {"success": False, "error": f"MongoDB MCP server '{server_name}' not found", "output": None}

        mcp_data = await call_mcp_tool(mcp, "query", {"command": command})
        return {"success": mcp_data.success, "output": mcp_data.result, "error": mcp_data.error}

    elif name.startswith("run_ssh_"):
        server_name = name[len("run_ssh_"):]
        command = args.get("command", "")

        # Safety check
        safety = is_shell_command_safe(command)
        if not safety.get("allowed"):
            return {"success": False, "error": f"Blocked: {safety.get('reason')}", "output": None}

        result = await db.execute(
            select(ServerConfig).where(
                ServerConfig.is_active == True,
                ServerConfig.name == server_name,
            )
        )
        server = result.scalar_one_or_none()
        if not server:
            return {"success": False, "error": f"SSH server '{server_name}' not found", "output": None}

        ssh_result = await run_ssh_command(server, command, use_sudo=False, timeout=30)
        return {
            "success": ssh_result.get("exit_code", 1) == 0,
            "output": ssh_result.get("stdout", ""),
            "error": ssh_result.get("stderr", ""),
        }

    else:
        return {"success": False, "error": f"Unknown tool: {name}", "output": None}
