from pydantic import BaseModel
from typing import Optional, List
from uuid import UUID
from datetime import datetime


class FoundryAgentConfigResponse(BaseModel):
    id: UUID
    agent_name: str
    foundry_agent_name: Optional[str] = None
    agent_line: str
    role: str
    system_type: str
    trigger_labels: dict = {}
    pipeline_order: int
    is_optional: bool
    is_active: bool
    description: Optional[str] = None
    config_json: dict = {}
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FoundryAgentConfigCreate(BaseModel):
    agent_name: str
    foundry_agent_name: Optional[str] = None
    agent_line: str = "workflow"
    role: str
    system_type: str = "all"
    trigger_labels: dict = {}
    pipeline_order: int = 0
    is_optional: bool = False
    is_active: bool = True
    description: Optional[str] = None
    config_json: dict = {}


class FoundryAgentConfigUpdate(BaseModel):
    agent_name: Optional[str] = None
    foundry_agent_name: Optional[str] = None
    agent_line: Optional[str] = None
    role: Optional[str] = None
    system_type: Optional[str] = None
    trigger_labels: Optional[dict] = None
    pipeline_order: Optional[int] = None
    is_optional: Optional[bool] = None
    is_active: Optional[bool] = None
    description: Optional[str] = None
    config_json: Optional[dict] = None


class FoundryConnectionTest(BaseModel):
    endpoint: Optional[str] = None  # override env if provided


class FoundryTestResult(BaseModel):
    success: bool
    message: str
    details: dict = {}
