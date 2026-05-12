from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.user import User
from app.models.mcp_config import MCPServerConfig
from app.schemas.mcp_config import (
    MCPServerConfigCreate,
    MCPServerConfigUpdate,
    MCPServerConfigResponse,
    MCPToolCallRequest,
    MCPToolCallResponse,
)
from app.auth.jwt_handler import require_admin, require_operator, get_current_user

router = APIRouter()


@router.get("/", response_model=list[MCPServerConfigResponse])
async def list_mcp_servers(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    result = await db.execute(select(MCPServerConfig).order_by(MCPServerConfig.name))
    configs = result.scalars().all()
    return [_to_response(c) for c in configs]


@router.get("/summary")
async def mcp_server_summary(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """Get high-level summary of MCP server health for dashboard."""
    from sqlalchemy import func
    
    total = (await db.execute(select(func.count(MCPServerConfig.id)))).scalar()
    healthy = (await db.execute(select(func.count(MCPServerConfig.id)).where(MCPServerConfig.health_status == "healthy"))).scalar()
    unhealthy = (await db.execute(select(func.count(MCPServerConfig.id)).where(MCPServerConfig.health_status == "unhealthy"))).scalar()
    unreachable = (await db.execute(select(func.count(MCPServerConfig.id)).where(MCPServerConfig.health_status == "unreachable"))).scalar()
    unknown = (await db.execute(select(func.count(MCPServerConfig.id)).where(MCPServerConfig.health_status.is_(None)))).scalar()
    
    return {
        "total": total,
        "healthy": healthy,
        "unhealthy": unhealthy,
        "unreachable": unreachable,
        "unknown": unknown
    }


@router.post("/", status_code=201)
async def create_mcp_server(
    payload: MCPServerConfigCreate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    result = await db.execute(select(MCPServerConfig).where(MCPServerConfig.name == payload.name))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="MCP server name already exists")
    config = MCPServerConfig(**payload.model_dump())
    # Run a connectivity check but don't block saving on failure.
    # Admins may configure connections before network routing is set up.
    from app.services.mcp_service import check_mcp_health
    from datetime import datetime, timezone
    health = {"status": "unknown", "error": None}
    try:
        health = await check_mcp_health(config)
    except Exception as e:
        health = {"status": "unhealthy", "error": f"Health check error: {e}"}
    config.last_health_check = datetime.now(timezone.utc)
    config.health_status = health.get("status", "unknown")
    if health.get("tools"):
        config.tools_available = health.get("tools")

    db.add(config)
    await db.flush()
    await db.refresh(config)
    response = _to_response(config)
    # Attach health detail so the UI can show a connectivity warning
    result = response.model_dump()
    result["health"] = health
    return result


@router.get("/{config_id}", response_model=MCPServerConfigResponse)
async def get_mcp_server(
    config_id: UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    result = await db.execute(select(MCPServerConfig).where(MCPServerConfig.id == config_id))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="MCP server not found")
    return _to_response(config)


@router.patch("/{config_id}", response_model=MCPServerConfigResponse)
async def update_mcp_server(
    config_id: UUID,
    payload: MCPServerConfigUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    result = await db.execute(select(MCPServerConfig).where(MCPServerConfig.id == config_id))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="MCP server not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(config, k, v)
    await db.flush()
    await db.refresh(config)
    return _to_response(config)


@router.delete("/{config_id}", status_code=204)
async def delete_mcp_server(
    config_id: UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    result = await db.execute(select(MCPServerConfig).where(MCPServerConfig.id == config_id))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="MCP server not found")
    await db.delete(config)


@router.post("/{config_id}/health-check")
async def health_check_mcp(
    config_id: UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    result = await db.execute(select(MCPServerConfig).where(MCPServerConfig.id == config_id))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="MCP server not found")
    from app.services.mcp_service import check_mcp_health
    health = await check_mcp_health(config)
    config.health_status = health["status"]
    from datetime import datetime, timezone
    config.last_health_check = datetime.now(timezone.utc)
    if health.get("tools"):
        config.tools_available = health["tools"]
    await db.flush()
    return health


@router.post("/call-tool", response_model=MCPToolCallResponse)
async def call_mcp_tool(
    payload: MCPToolCallRequest,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_operator),
):
    result = await db.execute(select(MCPServerConfig).where(MCPServerConfig.id == payload.server_id))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="MCP server not found")
    if not config.is_active:
        raise HTTPException(status_code=400, detail="MCP server is not active")
    from app.services.mcp_service import call_mcp_tool
    return await call_mcp_tool(config, payload.tool_name, payload.arguments)


@router.post("/test-connection")
async def test_connection(
    payload: MCPServerConfigCreate,
    _admin: User = Depends(require_admin),
):
    """Test database connectivity from raw form fields without saving."""
    config = MCPServerConfig(**payload.model_dump())
    from app.services.mcp_service import check_mcp_health
    try:
        health = await check_mcp_health(config)
    except Exception as e:
        health = {"status": "unhealthy", "error": f"Connection test error: {e}"}
    return health


def _to_response(config: MCPServerConfig) -> MCPServerConfigResponse:
    return MCPServerConfigResponse(
        id=config.id,
        name=config.name,
        description=config.description,
        server_type=config.server_type,
        command=config.command,
        args=config.args or [],
        env_vars=config.env_vars or {},
        connection_string=config.connection_string,
        oracle_host=config.oracle_host,
        oracle_port=config.oracle_port,
        oracle_service=config.oracle_service,
        oracle_user=config.oracle_user,
        has_password=bool(config.oracle_password),
        is_active=config.is_active,
        tools_available=config.tools_available or [],
        notification_emails=config.notification_emails or [],
        notification_cc=config.notification_cc or [],
        health_status=config.health_status,
        last_health_check=config.last_health_check,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )
