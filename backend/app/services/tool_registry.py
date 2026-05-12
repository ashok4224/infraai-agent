"""Tool registry — extensible data collection dispatch for Foundry pipeline.

This module now performs a safety gate for known mutating tools (SQL)
using `app.services.safety` before invoking the registered handler.
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


# ── Pre-register built-in tools ──


async def _oracle_sql_tool(config_id: str, sql: str) -> dict:
    """Execute Oracle SQL via existing MCP/oracledb infrastructure."""
    from uuid import UUID
    from sqlalchemy import select
    from app.database import async_session
    from app.models.mcp_config import MCPServerConfig
    from app.services.mcp_service import fetch_oracle_data

    async with async_session() as db:
        result = await db.execute(
            select(MCPServerConfig).where(MCPServerConfig.id == UUID(config_id))
        )
        config = result.scalar_one_or_none()
        if not config:
            return {"success": False, "error": f"MCP config {config_id} not found"}
        return await fetch_oracle_data(config, sql)


register_tool("oracle_sql", _oracle_sql_tool, system_type="oracle")
