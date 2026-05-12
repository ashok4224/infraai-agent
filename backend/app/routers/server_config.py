from uuid import UUID
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.user import User
from app.models.server_config import ServerConfig
from app.schemas.server_config import (
    ServerConfigCreate,
    ServerConfigUpdate,
    ServerConfigResponse,
    RunCommandRequest,
)
from app.auth.jwt_handler import require_admin, require_operator
from app.services.ssh_service import check_ssh_health, run_ssh_command

router = APIRouter()


# ── Helpers ────────────────────────────────────────────────────────────────


def _to_response(c: ServerConfig) -> ServerConfigResponse:
    return ServerConfigResponse(
        id=c.id,
        name=c.name,
        description=c.description,
        host=c.host,
        port=c.port,
        username=c.username,
        auth_type=c.auth_type,
        has_password=bool(c.ssh_password),
        has_private_key=bool(c.ssh_private_key),
        sudo_enabled=c.sudo_enabled,
        has_sudo_password=bool(c.sudo_password),
        os_type=c.os_type,
        tags=c.tags,
        is_active=c.is_active,
        health_status=c.health_status or "unknown",
        last_health_check=c.last_health_check,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


# ── CRUD ───────────────────────────────────────────────────────────────────


@router.get("/", response_model=list[ServerConfigResponse])
async def list_servers(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_operator),
):
    result = await db.execute(select(ServerConfig).order_by(ServerConfig.name))
    return [_to_response(c) for c in result.scalars().all()]


@router.post("/", status_code=201)
async def create_server(
    payload: ServerConfigCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    existing = await db.execute(select(ServerConfig).where(ServerConfig.name == payload.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Server name already exists")

    config = ServerConfig(**payload.model_dump())

    # Run health check but don't block save on failure
    health = await check_ssh_health(config)
    config.health_status = health.get("status", "unknown")
    config.last_health_check = datetime.now(timezone.utc)

    db.add(config)
    await db.flush()
    await db.refresh(config)

    result = _to_response(config).model_dump()
    result["health"] = health
    return result


@router.get("/{server_id}", response_model=ServerConfigResponse)
async def get_server(
    server_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(ServerConfig).where(ServerConfig.id == server_id))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Server not found")
    return _to_response(config)


@router.patch("/{server_id}", response_model=ServerConfigResponse)
async def update_server(
    server_id: UUID,
    payload: ServerConfigUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(ServerConfig).where(ServerConfig.id == server_id))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Server not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        # Don't overwrite credentials with empty string on update
        if v == "" and k in ("ssh_password", "ssh_private_key", "sudo_password"):
            continue
        setattr(config, k, v)
    await db.flush()
    await db.refresh(config)
    return _to_response(config)


@router.delete("/{server_id}", status_code=204)
async def delete_server(
    server_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(ServerConfig).where(ServerConfig.id == server_id))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Server not found")
    await db.delete(config)
    await db.flush()


# ── Actions ────────────────────────────────────────────────────────────────


@router.post("/{server_id}/health-check")
async def health_check_server(
    server_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(ServerConfig).where(ServerConfig.id == server_id))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Server not found")

    from app.services.ssh_service import check_ssh_health
    health = await check_ssh_health(config)
    config.health_status = health["status"]
    config.last_health_check = datetime.now(timezone.utc)
    await db.flush()
    return health


@router.post("/{server_id}/run-command")
async def run_command(
    server_id: UUID,
    payload: RunCommandRequest,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_operator),  # Operators can run commands
):
    result = await db.execute(select(ServerConfig).where(ServerConfig.id == server_id))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Server not found")
    if not config.is_active:
        raise HTTPException(status_code=400, detail="Server is not active")

    from app.services.ssh_service import run_ssh_command
    return await run_ssh_command(
        config,
        command=payload.command,
        use_sudo=payload.use_sudo,
        timeout=payload.timeout,
    )


@router.post("/test-connection")
async def test_server_connection(
    payload: ServerConfigCreate,
    _: User = Depends(require_admin),
):
    """Test SSH connectivity from raw form fields without saving."""
    config = ServerConfig(**payload.model_dump())
    return await check_ssh_health(config)
