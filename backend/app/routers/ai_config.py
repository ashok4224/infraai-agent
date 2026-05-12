from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.user import User
from app.models.ai_config import AIProviderConfig
from app.schemas.ai_config import AIProviderConfigCreate, AIProviderConfigUpdate, AIProviderConfigResponse
from app.auth.jwt_handler import require_admin

router = APIRouter()


@router.get("/", response_model=list[AIProviderConfigResponse])
async def list_providers(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    result = await db.execute(select(AIProviderConfig).order_by(AIProviderConfig.provider))
    configs = result.scalars().all()
    return [_to_response(c) for c in configs]


@router.post("/", response_model=AIProviderConfigResponse, status_code=201)
async def create_provider(
    payload: AIProviderConfigCreate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    result = await db.execute(select(AIProviderConfig).where(AIProviderConfig.provider == payload.provider))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Provider already exists")
    config = AIProviderConfig(**payload.model_dump())
    if payload.is_default:
        await _clear_defaults(db)
    db.add(config)
    await db.flush()
    await db.refresh(config)
    return _to_response(config)


@router.patch("/{config_id}", response_model=AIProviderConfigResponse)
async def update_provider(
    config_id: UUID,
    payload: AIProviderConfigUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    result = await db.execute(select(AIProviderConfig).where(AIProviderConfig.id == config_id))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Provider not found")
    update_data = payload.model_dump(exclude_unset=True)
    if update_data.get("is_default"):
        await _clear_defaults(db)
    for k, v in update_data.items():
        setattr(config, k, v)
    await db.flush()
    await db.refresh(config)
    return _to_response(config)


@router.delete("/{config_id}", status_code=204)
async def delete_provider(
    config_id: UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    result = await db.execute(select(AIProviderConfig).where(AIProviderConfig.id == config_id))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Provider not found")
    await db.delete(config)
    await db.flush()


@router.post("/{config_id}/test")
async def test_provider(
    config_id: UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    result = await db.execute(select(AIProviderConfig).where(AIProviderConfig.id == config_id))
    config = result.scalar_one_or_none()
    if not config:
        raise HTTPException(status_code=404, detail="Provider not found")
    from app.services.ai_service import test_ai_provider
    success, msg = await test_ai_provider(config)
    return {"success": success, "message": msg}


async def _clear_defaults(db: AsyncSession):
    result = await db.execute(select(AIProviderConfig).where(AIProviderConfig.is_default == True))
    for cfg in result.scalars().all():
        cfg.is_default = False


def _to_response(config: AIProviderConfig) -> AIProviderConfigResponse:
    return AIProviderConfigResponse(
        id=config.id,
        provider=config.provider,
        display_name=config.display_name,
        model_name=config.model_name,
        base_url=config.base_url,
        is_active=config.is_active,
        is_default=config.is_default,
        max_tokens=config.max_tokens,
        temperature=config.temperature,
        extra_params=config.extra_params,
        has_api_key=bool(config.api_key),
        created_at=config.created_at,
        updated_at=config.updated_at,
    )
