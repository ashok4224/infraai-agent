"""Fine-grained RBAC API — permissions, roles, user-role assignments."""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete, insert

from app.database import get_db
from app.models.user import User
from app.models.rbac import Permission, AppRole, role_permissions, user_roles
from app.schemas.rbac import (
    PermissionResponse,
    AppRoleCreate,
    AppRoleUpdate,
    AppRoleResponse,
    UserRoleAssign,
    UserWithRolesResponse,
)
from app.auth.jwt_handler import require_admin

router = APIRouter()


# ── Permissions (read-only — seeded, not user-created) ─────────────────────

@router.get("/permissions", response_model=list[PermissionResponse])
async def list_permissions(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(Permission).order_by(Permission.resource, Permission.action))
    return result.scalars().all()


# ── Roles ──────────────────────────────────────────────────────────────────

@router.get("/roles", response_model=list[AppRoleResponse])
async def list_roles(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(AppRole).order_by(AppRole.name))
    return result.scalars().all()


@router.post("/roles", status_code=201, response_model=AppRoleResponse)
async def create_role(
    payload: AppRoleCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    existing = await db.execute(select(AppRole).where(AppRole.name == payload.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Role name already exists")

    role = AppRole(
        name=payload.name,
        display_name=payload.display_name,
        description=payload.description,
        is_system=False,
    )
    db.add(role)
    await db.flush()

    if payload.permission_ids:
        perms = await db.execute(select(Permission).where(Permission.id.in_(payload.permission_ids)))
        role.permissions = list(perms.scalars().all())

    await db.flush()
    await db.refresh(role)
    return role


@router.get("/roles/{role_id}", response_model=AppRoleResponse)
async def get_role(
    role_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(AppRole).where(AppRole.id == role_id))
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    return role


@router.patch("/roles/{role_id}", response_model=AppRoleResponse)
async def update_role(
    role_id: UUID,
    payload: AppRoleUpdate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(AppRole).where(AppRole.id == role_id))
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.is_system:
        raise HTTPException(status_code=400, detail="System roles cannot be modified")

    if payload.name is not None:
        role.name = payload.name
    if payload.display_name is not None:
        role.display_name = payload.display_name
    if payload.description is not None:
        role.description = payload.description
    if payload.permission_ids is not None:
        perms = await db.execute(select(Permission).where(Permission.id.in_(payload.permission_ids)))
        role.permissions = list(perms.scalars().all())

    await db.flush()
    await db.refresh(role)
    return role


@router.delete("/roles/{role_id}", status_code=204)
async def delete_role(
    role_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    result = await db.execute(select(AppRole).where(AppRole.id == role_id))
    role = result.scalar_one_or_none()
    if not role:
        raise HTTPException(status_code=404, detail="Role not found")
    if role.is_system:
        raise HTTPException(status_code=400, detail="System roles cannot be deleted")
    await db.delete(role)
    await db.flush()


# ── User-Role Assignment ───────────────────────────────────────────────────

@router.get("/users", response_model=list[UserWithRolesResponse])
async def list_users_with_roles(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Return all users with their system role and custom role assignments."""
    users_result = await db.execute(select(User).order_by(User.full_name))
    users_list = users_result.scalars().all()

    response = []
    for user in users_list:
        roles_result = await db.execute(
            select(AppRole)
            .join(user_roles, AppRole.id == user_roles.c.role_id)
            .where(user_roles.c.user_id == user.id)
        )
        custom_roles = list(roles_result.scalars().all())
        response.append(UserWithRolesResponse(
            user_id=user.id,
            email=user.email,
            full_name=user.full_name,
            system_role=user.role,
            custom_roles=custom_roles,
        ))
    return response


@router.get("/users/{user_id}/roles", response_model=UserWithRolesResponse)
async def get_user_roles(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    roles_result = await db.execute(
        select(AppRole)
        .join(user_roles, AppRole.id == user_roles.c.role_id)
        .where(user_roles.c.user_id == user_id)
    )
    custom_roles = list(roles_result.scalars().all())
    return UserWithRolesResponse(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        system_role=user.role,
        custom_roles=custom_roles,
    )


@router.put("/users/{user_id}/roles", response_model=UserWithRolesResponse)
async def assign_user_roles(
    user_id: UUID,
    payload: UserRoleAssign,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Validate role IDs first
    if payload.role_ids:
        roles_result = await db.execute(select(AppRole).where(AppRole.id.in_(payload.role_ids)))
        valid_roles = list(roles_result.scalars().all())
        if len(valid_roles) != len(payload.role_ids):
            raise HTTPException(status_code=400, detail="One or more role IDs are invalid")

    # Replace all existing custom role assignments atomically
    await db.execute(delete(user_roles).where(user_roles.c.user_id == user_id))
    for rid in payload.role_ids:
        await db.execute(insert(user_roles).values(user_id=user_id, role_id=rid))

    await db.flush()

    roles_result = await db.execute(
        select(AppRole)
        .join(user_roles, AppRole.id == user_roles.c.role_id)
        .where(user_roles.c.user_id == user_id)
    )
    custom_roles = list(roles_result.scalars().all())
    return UserWithRolesResponse(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        system_role=user.role,
        custom_roles=custom_roles,
    )
