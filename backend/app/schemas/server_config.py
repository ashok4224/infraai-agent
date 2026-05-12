from pydantic import BaseModel, Field
from typing import Optional, Literal
from uuid import UUID
from datetime import datetime


class ServerConfigCreate(BaseModel):
    name: str
    description: Optional[str] = None
    host: str
    port: int = Field(22, ge=1, le=65535)
    username: str
    auth_type: Literal["password", "key"] = "password"
    ssh_password: Optional[str] = None
    ssh_private_key: Optional[str] = None  # PEM content
    sudo_enabled: bool = True
    sudo_password: Optional[str] = None
    os_type: str = "linux"
    tags: Optional[str] = None
    is_active: bool = True


class ServerConfigUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = Field(None, ge=1, le=65535)
    username: Optional[str] = None
    auth_type: Optional[Literal["password", "key"]] = None
    ssh_password: Optional[str] = None
    ssh_private_key: Optional[str] = None
    sudo_enabled: Optional[bool] = None
    sudo_password: Optional[str] = None
    os_type: Optional[str] = None
    tags: Optional[str] = None
    is_active: Optional[bool] = None


class ServerConfigResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    host: str
    port: int
    username: str
    auth_type: str
    has_password: bool = False
    has_private_key: bool = False
    sudo_enabled: bool
    has_sudo_password: bool = False
    os_type: str
    tags: Optional[str]
    is_active: bool
    health_status: str
    last_health_check: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RunCommandRequest(BaseModel):
    command: str
    use_sudo: bool = False
    timeout: int = 60
