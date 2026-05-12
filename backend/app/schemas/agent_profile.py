from pydantic import BaseModel
from typing import Optional
from uuid import UUID
from datetime import datetime


class AgentProfileCreate(BaseModel):
    name: str
    display_name: str
    description: Optional[str] = None
    system_prompt: str
    match_keywords: list[str] = []
    match_labels: dict = {}
    priority: int = 0
    # "os" = SSH/OS-commands only, "database" = MCP/SQL only, "general" = hybrid
    agent_type: str = "general"
    is_active: bool = True
    is_default: bool = False
    notification_emails: list[str] = []
    notification_cc: list[str] = []


class AgentProfileUpdate(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    match_keywords: Optional[list[str]] = None
    match_labels: Optional[dict] = None
    priority: Optional[int] = None
    agent_type: Optional[str] = None
    is_active: Optional[bool] = None
    is_default: Optional[bool] = None
    notification_emails: Optional[list[str]] = None
    notification_cc: Optional[list[str]] = None


class AgentProfileResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: UUID
    name: str
    display_name: str
    description: Optional[str]
    system_prompt: str
    match_keywords: list
    match_labels: dict
    priority: int
    agent_type: str
    is_active: bool
    is_default: bool
    notification_emails: list
    notification_cc: list
    created_at: datetime
    updated_at: datetime
