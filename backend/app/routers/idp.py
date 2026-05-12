"""Identity Provider admin CRUD router."""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.user import User
from app.models.idp import IdentityProvider
from app.schemas.idp import (
    IdentityProviderCreate,
    IdentityProviderUpdate,
    IdentityProviderResponse,
)
from app.auth.jwt_handler import require_admin

router = APIRouter()


@router.get("/", response_model=list[IdentityProviderResponse])
async def list_idps(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(
        select(IdentityProvider).order_by(IdentityProvider.name)
    )
    return result.scalars().all()


@router.post("/", response_model=IdentityProviderResponse, status_code=201)
async def create_idp(
    payload: IdentityProviderCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    if payload.protocol not in ("oidc", "saml"):
        raise HTTPException(status_code=400, detail="Protocol must be 'oidc' or 'saml'")

    existing = await db.execute(
        select(IdentityProvider).where(IdentityProvider.name == payload.name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="IDP name already exists")

    # If setting as default, clear existing default
    if payload.is_default:
        await _clear_default(db)

    idp = IdentityProvider(**payload.model_dump())
    db.add(idp)
    await db.flush()
    await db.refresh(idp)
    return idp


@router.get("/{idp_id}", response_model=IdentityProviderResponse)
async def get_idp(
    idp_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(
        select(IdentityProvider).where(IdentityProvider.id == idp_id)
    )
    idp = result.scalar_one_or_none()
    if not idp:
        raise HTTPException(status_code=404, detail="Identity provider not found")
    return idp


@router.patch("/{idp_id}", response_model=IdentityProviderResponse)
async def update_idp(
    idp_id: UUID,
    payload: IdentityProviderUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(
        select(IdentityProvider).where(IdentityProvider.id == idp_id)
    )
    idp = result.scalar_one_or_none()
    if not idp:
        raise HTTPException(status_code=404, detail="Identity provider not found")

    update_data = payload.model_dump(exclude_unset=True)

    # If setting as default, clear existing default
    if update_data.get("is_default"):
        await _clear_default(db, exclude_id=idp_id)

    # Don't overwrite secrets with empty/masked values
    for secret_field in ("oidc_client_secret", "saml_certificate", "scim_token"):
        val = update_data.get(secret_field)
        if val is not None and (not val or val == "••••••••"):
            del update_data[secret_field]

    for k, v in update_data.items():
        setattr(idp, k, v)

    await db.flush()
    await db.refresh(idp)
    return idp


@router.delete("/{idp_id}", status_code=204)
async def delete_idp(
    idp_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(
        select(IdentityProvider).where(IdentityProvider.id == idp_id)
    )
    idp = result.scalar_one_or_none()
    if not idp:
        raise HTTPException(status_code=404, detail="Identity provider not found")
    await db.delete(idp)
    await db.flush()


@router.post("/{idp_id}/test")
async def test_idp(
    idp_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Test IDP connectivity (OIDC: fetch discovery; SAML: fetch/parse metadata)."""
    result = await db.execute(
        select(IdentityProvider).where(IdentityProvider.id == idp_id)
    )
    idp = result.scalar_one_or_none()
    if not idp:
        raise HTTPException(status_code=404, detail="Identity provider not found")

    if idp.protocol == "oidc":
        from app.services.oidc_service import test_oidc_connection
        return await test_oidc_connection(idp)
    elif idp.protocol == "saml":
        from app.services.saml_service import test_saml_connection
        return await test_saml_connection(idp)

    return {"success": False, "error": f"Unknown protocol: {idp.protocol}"}


async def _clear_default(db: AsyncSession, exclude_id: UUID | None = None):
    """Clear the is_default flag on all IDPs (optionally excluding one)."""
    query = select(IdentityProvider).where(IdentityProvider.is_default == True)
    if exclude_id:
        query = query.where(IdentityProvider.id != exclude_id)
    result = await db.execute(query)
    for idp in result.scalars().all():
        idp.is_default = False
