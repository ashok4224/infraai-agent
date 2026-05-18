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
    """Execute a PostgreSQL query — direct driver first, MCP subprocess as fallback."""
    config = await _load_mcp_config(config_id)
    if config is None:
        return {"success": False, "error": f"MCP config {config_id} not found"}

    # Try direct connection first (faster, no subprocess overhead)
    from app.services.mcp_service import _build_pg_dsn
    import asyncio

    pg_dsn = _build_pg_dsn(config) or (config.connection_string or "")

    if pg_dsn:
        # asyncpg: accepts both postgresql:// URL and libpq key=value format
        try:
            import asyncpg
            if pg_dsn.startswith("postgresql://") or pg_dsn.startswith("postgres://"):
                conn = await asyncio.wait_for(asyncpg.connect(dsn=pg_dsn), timeout=10)
            else:
                # libpq format — parse into individual params
                import re
                kv = dict(re.findall(r"(\w+)=([^\s]+)", pg_dsn))
                conn = await asyncio.wait_for(
                    asyncpg.connect(
                        host=kv.get("host", config.oracle_host),
                        port=int(kv.get("port", config.oracle_port or 5432)),
                        database=kv.get("dbname", config.oracle_service or "postgres"),
                        user=kv.get("user", config.oracle_user),
                        password=kv.get("password", config.oracle_password or ""),
                    ),
                    timeout=10,
                )
            rows = await conn.fetch(sql.strip().rstrip(";"))
            columns = list(rows[0].keys()) if rows else []
            await conn.close()
            logger.info("PostgreSQL MCP query succeeded via asyncpg on '%s'", config.name)
            return {"success": True, "data": {"columns": columns, "rows": [list(r.values()) for r in rows]}}
        except ImportError:
            pass
        except Exception as e:
            logger.warning("asyncpg direct connection failed on '%s': %s — trying psycopg2", config.name, e)

        # psycopg2 fallback
        try:
            import psycopg2
            def _run():
                conn = psycopg2.connect(pg_dsn, connect_timeout=10)
                cur = conn.cursor()
                cur.execute(sql.strip().rstrip(";"))
                cols = [d[0] for d in cur.description] if cur.description else []
                result_rows = cur.fetchall()
                cur.close()
                conn.close()
                return {"columns": cols, "rows": [list(r) for r in result_rows]}
            data = await asyncio.wait_for(asyncio.to_thread(_run), timeout=20.0)
            logger.info("PostgreSQL MCP query succeeded via psycopg2 on '%s'", config.name)
            return {"success": True, "data": data}
        except ImportError:
            pass
        except Exception as e:
            logger.warning("psycopg2 direct connection failed on '%s': %s — falling back to MCP subprocess", config.name, e)

    # Fallback: MCP subprocess (requires npx in container PATH)
    if config.command and config.command.strip():
        return await _mcp_call_tool(config_id, "pg_query", {"sql": sql})

    return {"success": False, "error": f"[{config.name}] No working PostgreSQL connection — no direct driver succeeded and no MCP command configured"}


# ── MySQL generic executor ──
async def _mysql_query_tool(config_id: str, sql: str) -> dict:
    """Execute a MySQL query via direct driver or MCP subprocess."""
    config = await _load_mcp_config(config_id)
    if config is None:
        return {"success": False, "error": f"MCP config {config_id} not found"}

    # Build MySQL connection params from MCP config
    host = config.oracle_host or "localhost"
    port = config.oracle_port or 3306
    user = config.oracle_user or "root"
    password = config.oracle_password or ""
    db = config.oracle_service or "mysql"

    try:
        import aiomysql
        conn = await aiomysql.connect(host=host, port=port, user=user, password=password, db=db)
        cursor = await conn.cursor()
        await cursor.execute(sql)
        rows = await cursor.fetchall()
        cols = [d[0] for d in cursor.description] if cursor.description else []
        await cursor.close()
        conn.close()
        return {"success": True, "data": {"columns": cols, "rows": [list(r) for r in rows]}}
    except ImportError:
        try:
            import pymysql
            def _run():
                conn = pymysql.connect(host=host, port=port, user=user, password=password, database=db)
                cur = conn.cursor()
                cur.execute(sql)
                cols = [d[0] for d in cur.description] if cur.description else []
                rows = cur.fetchall()
                cur.close()
                conn.close()
                return {"columns": cols, "rows": [list(r) for r in rows]}
            data = await __import__("asyncio").to_thread(_run)
            return {"success": True, "data": data}
        except Exception as e:
            return {"success": False, "error": str(e)}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── MongoDB generic executor ──
async def _mongodb_query_tool(config_id: str, sql: str) -> dict:
    """Execute a MongoDB query (shell syntax) via direct pymongo or MCP subprocess."""
    config = await _load_mcp_config(config_id)
    if config is None:
        return {"success": False, "error": f"MCP config {config_id} not found"}

    host = config.oracle_host or "localhost"
    port = config.oracle_port or 27017
    user = config.oracle_user or None
    password = config.oracle_password or None
    db_name = config.oracle_service or "admin"

    try:
        import pymongo
        from urllib.parse import quote_plus

        if user and password:
            uri = f"mongodb://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/"
        else:
            uri = f"mongodb://{host}:{port}/"

        client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=5000)
        db = client[db_name]

        # Try to execute as eval (JavaScript) or as aggregation pipeline
        try:
            result = list(db.command("eval", {"code": f"function() {{ return JSON.stringify({sql}); }}"}))

        except Exception:
            result = [{"note": "Query syntax not recognized", "query": sql}]

        client.close()
        return {"success": True, "data": result}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Slack executor ──
async def _slack_send_tool(config_id: str, text: str, channel: str = None) -> dict:
    """Send a message to Slack via MCP or webhook."""
    config = await _load_mcp_config(config_id)
    if config is None:
        return {"success": False, "error": f"MCP config {config_id} not found"}

    webhook = (config.env_vars or {}).get("SLACK_WEBHOOK_URL", "")
    if webhook:
        import httpx
        payload = {"text": text}
        if channel:
            payload["channel"] = channel
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(webhook, json=payload, timeout=10.0)
                return {"success": resp.status_code < 400, "status": resp.status_code}
        except Exception as e:
            return {"success": False, "error": str(e)}

    return await _mcp_call_tool(config_id, "slack_send", {"text": text, "channel": channel or ""})


# ── Prometheus executor ──
async def _prometheus_query_tool(config_id: str, query: str) -> dict:
    """Query Prometheus metrics via HTTP API."""
    config = await _load_mcp_config(config_id)
    if config is None:
        return {"success": False, "error": f"MCP config {config_id} not found"}

    url = (config.env_vars or {}).get("PROMETHEUS_URL", "")
    if not url:
        return {"success": False, "error": "PROMETHEUS_URL not configured"}

    import httpx
    api_url = f"{url.rstrip('/')}/api/v1/query"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(api_url, params={"query": query})
            data = resp.json()
            if data.get("status") == "success":
                return {"success": True, "data": data["data"]["result"]}
            return {"success": False, "error": data.get("error", "Unknown error")}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Register all tools ──

register_tool("oracle_sql",       _oracle_sql_tool,        system_type="oracle")
register_tool("ssh_exec",         _ssh_exec_tool,           system_type="os")
register_tool("aws_exec",         _aws_exec_tool,           system_type="aws")
register_tool("azure_exec",       _azure_exec_tool,         system_type="azure")
register_tool("k8s_exec",         _k8s_exec_tool,           system_type="kubernetes")
register_tool("postgres_query",   _postgres_query_tool,     system_type="postgresql")
register_tool("mysql_query",      _mysql_query_tool,        system_type="mysql")
register_tool("mongodb_query",    _mongodb_query_tool,      system_type="mongodb")
register_tool("slack_send",       _slack_send_tool,         system_type="notification")
register_tool("prometheus_query", _prometheus_query_tool,   system_type="prometheus")

logger.info("Tool registry loaded: %d tools registered", len(_tools))