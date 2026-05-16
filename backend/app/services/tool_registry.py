"""Tool registry — extensible data collection dispatch for Foundry pipeline.

This module now performs a safety gate for known mutating tools (SQL)
using `app.services.safety` before invoking the registered handler.

Phase 1: Added AWS, Azure, Kubernetes, SSH, PostgreSQL generic executors.
"""
import logging
from typing import Callable, Awaitable

from app.services.safety import is_sql_safe

logger = logging.getLogger(__name__)

# Registry: tool_name → (handler_fn, system_type)
_tools: dict[str, tuple[Callable[..., Awaitable[dict]], str]] = {}


def register_tool(name: str, handler: Callable[..., Awaitable[dict]], system_type: str = "all"):
    """Register a data collection tool."""
    _tools[name] = (handler, system_type)
    logger.info("Registered tool: %s (system_type=%s)", name, system_type)


async def execute_tool(name: str, params: dict) -> dict:
    """Execute a registered tool by name with a safety gate for SQL tools."""
    if name not in _tools:
        return {"success": False, "error": f"Unknown tool: {name}"}
    handler, system_type = _tools[name]

    # Safety gate for SQL-like tools
    if name in ("oracle_sql",):
        sql = (params or {}).get("sql", "") or ""
        check = is_sql_safe(sql)
        if not check.get("allowed"):
            return {
                "success": False,
                "error": "Refused to run unsafe SQL",
                "requires_approval": check.get("requires_approval", True),
                "reason": check.get("reason"),
                "risk": check.get("risk"),
            }

    try:
        return await handler(**params)
    except Exception as e:
        logger.error("Tool '%s' execution failed: %s", name, e)
        return {"success": False, "error": str(e)}


def list_tools() -> list[dict]:
    """List all registered tools."""
    return [
        {"name": name, "system_type": system_type}
        for name, (_, system_type) in _tools.items()
    ]


def get_tools_for_system(system_type: str) -> list[str]:
    """Get tool names available for a given system type."""
    return [
        name for name, (_, st) in _tools.items()
        if st == "all" or st == system_type
    ]


# ──────────────────────────────────────────────────────────────────────────────
# Generic MCP tool dispatcher — works with ANY MCP server
# ──────────────────────────────────────────────────────────────────────────────

async def _load_mcp_config(config_id: str):
    """Resolve an MCP server config by ID from the database."""
    from uuid import UUID
    from sqlalchemy import select
    from app.database import async_session
    from app.models.mcp_config import MCPServerConfig

    async with async_session() as db:
        result = await db.execute(
            select(MCPServerConfig).where(MCPServerConfig.id == UUID(config_id))
        )
        config = result.scalar_one_or_none()
        if not config:
            return None
        return config


async def _mcp_call_tool(config_id: str, tool_name: str, arguments: dict = None) -> dict:
    """Execute any named tool on an MCP server via the universal MCPClient."""
    config = await _load_mcp_config(config_id)
    if config is None:
        return {"success": False, "error": f"MCP config {config_id} not found"}

    from app.services.mcp_service import get_mcp_client
    try:
        client = await get_mcp_client(config)
        response = await client.call_tool(tool_name, arguments or {})
        if "error" in response:
            return {"success": False, "error": response["error"].get("message", "Unknown MCP error")}
        return {"success": True, "data": response.get("result")}
    except Exception as e:
        logger.error("MCP tool '%s' failed on '%s': %s", tool_name, config.name, e)
        return {"success": False, "error": str(e)}


# ──────────────────────────────────────────────────────────────────────────────
# Built-in tool handlers
# ──────────────────────────────────────────────────────────────────────────────

async def _oracle_sql_tool(config_id: str, sql: str) -> dict:
    """Execute Oracle SQL via existing MCP/oracledb infrastructure."""
    config = await _load_mcp_config(config_id)
    if config is None:
        return {"success": False, "error": f"MCP config {config_id} not found"}
    from app.services.mcp_service import fetch_oracle_data
    return await fetch_oracle_data(config, sql)


# ── SSH / OS exec tool ──
async def _ssh_exec_tool(config_id: str, command: str, timeout: int = 30) -> dict:
    """Execute a shell command on a matched SSH server (ServerConfig)."""
    from uuid import UUID
    from sqlalchemy import select
    from app.database import async_session
    from app.models.server_config import ServerConfig
    from app.services.ssh_service import run_ssh_command

    async with async_session() as db:
        result = await db.execute(
            select(ServerConfig).where(ServerConfig.id == UUID(config_id), ServerConfig.is_active == True)
        )
        server = result.scalar_one_or_none()
        if not server:
            return {"success": False, "error": f"Server config {config_id} not found or inactive"}
        return await run_ssh_command(server, command, use_sudo=False, timeout=timeout)


# ── AWS generic executor ──
async def _aws_exec_tool(config_id: str, service: str, operation: str, region: str = None, params: dict = None) -> dict:
    """Execute any AWS API call via the aws-mcp-server.

    Args:
        config_id: MCP server config ID (server_type="aws")
        service: AWS service name (ec2, cloudwatch, rds, elb, eks, s3, lambda, iam)
        operation: Operation name (describe_instances, get_metric_statistics, ...)
        region: AWS region override (defaults to env var)
        params: Additional keyword parameters for the boto3 call
    """
    tool_args = {
        "service": service,
        "operation": operation,
        "params": params or {},
    }
    if region:
        tool_args["region"] = region
    return await _mcp_call_tool(config_id, "aws_exec", tool_args)


# ── Azure generic executor ──
async def _azure_exec_tool(config_id: str, service: str, operation: str, resource_group: str = None, subscription_id: str = None, params: dict = None) -> dict:
    """Execute any Azure API call via the azure-mcp-server.

    Args:
        config_id: MCP server config ID (server_type="azure")
        service: Azure service (compute, monitor, aks, sql, appservice)
        operation: Operation (list_vms, get_metrics, get_cluster)
        resource_group: Azure resource group
        subscription_id: Azure subscription ID override
        params: Additional keyword parameters
    """
    tool_args = {
        "service": service,
        "operation": operation,
        "params": params or {},
    }
    if resource_group:
        tool_args["resource_group"] = resource_group
    if subscription_id:
        tool_args["subscription_id"] = subscription_id
    return await _mcp_call_tool(config_id, "azure_exec", tool_args)


# ── Kubernetes generic executor ──
async def _k8s_exec_tool(config_id: str, verb: str, resource: str, namespace: str = None, extra_args: list = None) -> dict:
    """Execute any kubectl command via the k8s-mcp-server.

    Args:
        config_id: MCP server config ID (server_type="kubernetes")
        verb: kubectl verb (get, describe, logs, top, events)
        resource: k8s resource (pod/podname, nodes, deployments, services, events)
        namespace: k8s namespace (optional)
        extra_args: Additional kubectl flags (e.g., ["--tail=100", "-o", "json"])
    """
    tool_args = {
        "verb": verb,
        "resource": resource,
    }
    if namespace:
        tool_args["namespace"] = namespace
    if extra_args:
        tool_args["extra_args"] = extra_args
    return await _mcp_call_tool(config_id, "k8s_exec", tool_args)


# ── PostgreSQL generic executor ──
async def _postgres_query_tool(config_id: str, sql: str) -> dict:
    """Execute a PostgreSQL query via MCP or direct driver."""
    config = await _load_mcp_config(config_id)
    if config is None:
        return {"success": False, "error": f"MCP config {config_id} not found"}

    # Try MCP subprocess first, fall back to direct driver
    if config.command and config.command.strip():
        return await _mcp_call_tool(config_id, "pg_query", {"sql": sql})

    # Direct connection fallback
    from app.services.mcp_service import _build_pg_dsn, _test_direct_postgresql
    import asyncio

    pg_dsn = _build_pg_dsn(config)
    if not pg_dsn:
        return {"success": False, "error": "No PostgreSQL connection info configured"}

    try:
        import asyncpg
        conn = await asyncpg.connect(pg_dsn)
        rows = await conn.fetch(sql)
        columns = list(rows[0].keys()) if rows else []
        await conn.close()
        return {"success": True, "data": {"columns": columns, "rows": [list(r.values()) for r in rows]}}
    except ImportError:
        try:
            import psycopg2
            def _run():
                conn = psycopg2.connect(pg_dsn)
                cur = conn.cursor()
                cur.execute(sql)
                cols = [d[0] for d in cur.description] if cur.description else []
                rows = cur.fetchall()
                cur.close()
                conn.close()
                return {"columns": cols, "rows": [list(r) for r in rows]}
            data = await asyncio.to_thread(_run)
            return {"success": True, "data": data}
        except Exception as e:
            return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Register all tools ──

register_tool("oracle_sql",       _oracle_sql_tool,   system_type="oracle")
register_tool("ssh_exec",         _ssh_exec_tool,     system_type="os")
register_tool("aws_exec",         _aws_exec_tool,     system_type="aws")
register_tool("azure_exec",       _azure_exec_tool,   system_type="azure")
register_tool("k8s_exec",         _k8s_exec_tool,     system_type="kubernetes")
register_tool("postgres_query",   _postgres_query_tool, system_type="postgresql")

logger.info("Tool registry loaded: %d tools registered", len(_tools))