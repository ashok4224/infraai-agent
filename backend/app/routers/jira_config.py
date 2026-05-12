from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timezone

from app.database import get_db
from app.models.user import User
from app.models.jira_config import JiraConfig
from app.schemas.jira_config import (
    JiraConfigCreate,
    JiraConfigUpdate,
    JiraConfigResponse,
    JiraSearchRequest,
    JiraSearchResponse,
)
from app.auth.jwt_handler import require_admin, require_operator, get_current_user

router = APIRouter()


@router.get("/", response_model=list[JiraConfigResponse])
async def list_jira_configs(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    result = await db.execute(select(JiraConfig).order_by(JiraConfig.name))
    configs = result.scalars().all()
    return [_to_response(c) for c in configs]


@router.get("/summary")
async def jira_config_summary(
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """High-level summary for the dashboard."""
    from sqlalchemy import func
    total = (await db.execute(select(func.count(JiraConfig.id)))).scalar()
    healthy = (await db.execute(select(func.count(JiraConfig.id)).where(JiraConfig.health_status == "healthy"))).scalar()
    return {"total": total, "healthy": healthy}


@router.post("/", status_code=201)
async def create_jira_config(
    payload: JiraConfigCreate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    result = await db.execute(select(JiraConfig).where(JiraConfig.name == payload.name))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Jira config name already exists")

    config = JiraConfig(**payload.model_dump())

    # Run connectivity check
    from app.services.jira_service import check_jira_health
    health = {"status": "unknown", "error": None}
    try:
        health = await check_jira_health(config)
    except Exception as e:
        health = {"status": "unhealthy", "error": f"Health check error: {e}"}
    config.last_health_check = datetime.now(timezone.utc)
    config.health_status = health.get("status", "unknown")

    db.add(config)
    await db.flush()
    await db.refresh(config)
    response = _to_response(config)
    result_data = response.model_dump()
    result_data["health"] = health
    return result_data


@router.get("/{config_id}", response_model=JiraConfigResponse)
async def get_jira_config(
    config_id: UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    result = await db.execute(select(JiraConfig).where(JiraConfig.id == config_id))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Jira config not found")
    return _to_response(config)


@router.patch("/{config_id}", response_model=JiraConfigResponse)
async def update_jira_config(
    config_id: UUID,
    payload: JiraConfigUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    result = await db.execute(select(JiraConfig).where(JiraConfig.id == config_id))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Jira config not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(config, k, v)
    await db.flush()
    await db.refresh(config)
    return _to_response(config)


@router.delete("/{config_id}", status_code=204)
async def delete_jira_config(
    config_id: UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    result = await db.execute(select(JiraConfig).where(JiraConfig.id == config_id))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Jira config not found")
    await db.delete(config)


@router.post("/{config_id}/health-check")
async def health_check_jira(
    config_id: UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    result = await db.execute(select(JiraConfig).where(JiraConfig.id == config_id))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Jira config not found")
    from app.services.jira_service import check_jira_health
    health = await check_jira_health(config)
    config.health_status = health.get("status", "unknown")
    config.last_health_check = datetime.now(timezone.utc)
    await db.flush()
    return health


@router.post("/test-connection")
async def test_jira_connection(
    payload: JiraConfigCreate,
    _admin: User = Depends(require_admin),
):
    """Test Jira connectivity from raw form fields without saving."""
    config = JiraConfig(**payload.model_dump())
    from app.services.jira_service import check_jira_health
    try:
        health = await check_jira_health(config)
    except Exception as e:
        health = {"status": "unhealthy", "error": f"Connection test error: {e}"}
    return health


@router.post("/search")
async def search_jira_issues(
    payload: JiraSearchRequest,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_operator),
):
    """Manual issue search from the UI."""
    result = await db.execute(select(JiraConfig).where(JiraConfig.id == payload.config_id))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Jira config not found")
    if not config.is_active:
        raise HTTPException(status_code=400, detail="Jira config is not active")
    from app.services.jira_service import search_similar_issues
    return await search_similar_issues(config, payload.query, payload.max_results)


@router.post("/search-kb")
async def search_jira_kb(
    payload: JiraSearchRequest,
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(require_operator),
):
    """Search Jira Service Management knowledge base articles."""
    result = await db.execute(select(JiraConfig).where(JiraConfig.id == payload.config_id))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Jira config not found")
    if not config.is_active:
        raise HTTPException(status_code=400, detail="Jira config is not active")
    from app.services.jira_service import search_jsm_knowledge_base
    return await search_jsm_knowledge_base(config, payload.query, payload.max_results)


def _to_response(config: JiraConfig) -> JiraConfigResponse:
    return JiraConfigResponse(
        id=config.id,
        name=config.name,
        description=config.description,
        instance_type=config.instance_type,
        base_url=config.base_url,
        auth_email=config.auth_email,
        has_token=bool(config.api_token),
        project_keys=config.project_keys or [],
        jsm_enabled=config.jsm_enabled,
        jsm_service_desk_id=config.jsm_service_desk_id,
        kb_enabled=config.kb_enabled,
        kb_space_keys=config.kb_space_keys or [],
        max_results=config.max_results,
        issue_types_filter=config.issue_types_filter or [],
        status_filter=config.status_filter or [],
        label_filter=config.label_filter or [],
        is_active=config.is_active,
        health_status=config.health_status or "unknown",
        last_health_check=config.last_health_check,
        created_at=config.created_at,
        updated_at=config.updated_at,
    )
