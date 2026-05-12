from pydantic import BaseModel
from typing import Optional, List
from uuid import UUID
from datetime import datetime


class MCPServerConfigCreate(BaseModel):
    name: str
    description: Optional[str] = None
    server_type: str = "sqlcl"
    command: str = "sql"
    args: list = []
    env_vars: dict = {}
    connection_string: Optional[str] = None
    oracle_host: Optional[str] = None
    oracle_port: int = 1521
    oracle_service: Optional[str] = None
    oracle_user: Optional[str] = None
    oracle_password: Optional[str] = None
    is_active: bool = True
    tools_available: list = []
    notification_emails: list[str] = []
    notification_cc: list[str] = []


class MCPServerConfigUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    server_type: Optional[str] = None
    command: Optional[str] = None
    args: Optional[list] = None
    env_vars: Optional[dict] = None
    connection_string: Optional[str] = None
    oracle_host: Optional[str] = None
    oracle_port: Optional[int] = None
    oracle_service: Optional[str] = None
    oracle_user: Optional[str] = None
    oracle_password: Optional[str] = None
    is_active: Optional[bool] = None
    tools_available: Optional[list] = None
    notification_emails: Optional[list[str]] = None
    notification_cc: Optional[list[str]] = None


class MCPServerConfigResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    server_type: str
    command: str
    args: list
    env_vars: dict
    connection_string: Optional[str]
    oracle_host: Optional[str]
    oracle_port: Optional[int]
    oracle_service: Optional[str]
    oracle_user: Optional[str]
    has_password: bool = False
    is_active: bool
    tools_available: list
    notification_emails: list
    notification_cc: list
    health_status: str
    last_health_check: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MCPToolCallRequest(BaseModel):
    server_id: UUID
    tool_name: str
    arguments: dict = {}


class MCPToolCallResponse(BaseModel):
    success: bool
    result: Optional[dict] = None
    error: Optional[str] = None
