from pydantic import BaseModel
from typing import Optional, List
from uuid import UUID
from datetime import datetime


class PermissionResponse(BaseModel):
    id: UUID
    name: str
    display_name: str
    resource: str
    action: str
    description: Optional[str]

    model_config = {"from_attributes": True}


class AppRoleCreate(BaseModel):
    name: str
    display_name: str
    description: Optional[str] = None
    permission_ids: List[UUID] = []


class AppRoleUpdate(BaseModel):
    name: Optional[str] = None
    display_name: Optional[str] = None
    description: Optional[str] = None
    permission_ids: Optional[List[UUID]] = None


class AppRoleResponse(BaseModel):
    id: UUID
    name: str
    display_name: str
    description: Optional[str]
    is_system: bool
    mfa_required: bool = False
    permissions: List[PermissionResponse] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserRoleAssign(BaseModel):
    role_ids: List[UUID]


class UserWithRolesResponse(BaseModel):
    user_id: UUID
    email: str
    full_name: str
    system_role: str        # built-in role: admin / operator / viewer
    custom_roles: List[AppRoleResponse] = []
