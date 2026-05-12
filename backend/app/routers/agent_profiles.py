from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.user import User
from app.models.agent_profile import AgentProfile
from app.schemas.agent_profile import AgentProfileCreate, AgentProfileUpdate, AgentProfileResponse
from app.auth.jwt_handler import require_admin

router = APIRouter()


@router.get("/", response_model=list[AgentProfileResponse])
async def list_profiles(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    result = await db.execute(select(AgentProfile).order_by(AgentProfile.priority.desc(), AgentProfile.name))
    return result.scalars().all()


@router.post("/", response_model=AgentProfileResponse, status_code=201)
async def create_profile(
    payload: AgentProfileCreate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    result = await db.execute(select(AgentProfile).where(AgentProfile.name == payload.name))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Agent profile with this name already exists")
    if payload.is_default:
        await _clear_defaults(db)
    profile = AgentProfile(**payload.model_dump())
    db.add(profile)
    await db.flush()
    await db.refresh(profile)
    return profile


@router.get("/{profile_id}", response_model=AgentProfileResponse)
async def get_profile(
    profile_id: UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    result = await db.execute(select(AgentProfile).where(AgentProfile.id == profile_id))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Agent profile not found")
    return profile


@router.patch("/{profile_id}", response_model=AgentProfileResponse)
async def update_profile(
    profile_id: UUID,
    payload: AgentProfileUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    result = await db.execute(select(AgentProfile).where(AgentProfile.id == profile_id))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Agent profile not found")
    update_data = payload.model_dump(exclude_unset=True)
    if update_data.get("is_default"):
        await _clear_defaults(db)
    for k, v in update_data.items():
        setattr(profile, k, v)
    await db.flush()
    await db.refresh(profile)
    return profile


@router.delete("/{profile_id}", status_code=204)
async def delete_profile(
    profile_id: UUID,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    result = await db.execute(select(AgentProfile).where(AgentProfile.id == profile_id))
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Agent profile not found")
    await db.delete(profile)
    await db.flush()


async def _clear_defaults(db: AsyncSession):
    result = await db.execute(select(AgentProfile).where(AgentProfile.is_default == True))
    for p in result.scalars().all():
        p.is_default = False
