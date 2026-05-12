"""Schemas for command execution approval workflow."""
from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID
from datetime import datetime


class CommandExecutionRequest(BaseModel):
    """Request to execute a command (submitted from AskMe chat or alert fix_commands)."""
    command: str = Field(..., min_length=1, max_length=10000)
    description: str = Field(..., min_length=1, max_length=1000)
    target_type: str = Field(..., pattern=r"^(sql|os|config)$")
    target_server_id: Optional[UUID] = None
    target_server_name: Optional[str] = None
    risk_level: str = Field(default="Medium", pattern=r"^(Low|Medium|High|Critical)$")
    alert_id: Optional[UUID] = None
    chat_session_id: Optional[UUID] = None


class CommandApprovalAction(BaseModel):
    """Admin approves or rejects a pending command."""
    action: str = Field(..., pattern=r"^(approve|reject)$")
    note: Optional[str] = Field(None, max_length=1000)


class CommandExecutionResponse(BaseModel):
    id: UUID
    requested_by_email: str
    alert_id: Optional[UUID] = None
    chat_session_id: Optional[UUID] = None
    target_type: str
    target_server_id: Optional[UUID] = None
    target_server_name: Optional[str] = None
    command: str
    description: str
    risk_level: str
    status: str
    approved_by_email: Optional[str] = None
    approval_note: Optional[str] = None
    approved_at: Optional[datetime] = None
    executed_at: Optional[datetime] = None
    execution_result: dict = {}
    execution_duration_ms: Optional[int] = None
    created_at: datetime
    expires_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class CommandExecutionListResponse(BaseModel):
    commands: list[CommandExecutionResponse]
    total: int
    page: int
    per_page: int
