from pydantic import BaseModel, Field
from typing import Optional, List
from uuid import UUID
from datetime import datetime


class ChatMessageResponse(BaseModel):
    id: UUID
    session_id: UUID
    role: str
    content: str
    metadata_json: Optional[dict] = {}
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatSessionResponse(BaseModel):
    id: UUID
    user_id: UUID
    title: str
    ai_mode: str
    created_at: datetime
    updated_at: datetime
    messages: List[ChatMessageResponse] = []

    model_config = {"from_attributes": True}


class ChatSessionListItem(BaseModel):
    id: UUID
    title: str
    ai_mode: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0

    model_config = {"from_attributes": True}


class ToolCallItem(BaseModel):
    type: str  # "sql" or "ssh"
    server_name: str
    query: Optional[str] = None
    command: Optional[str] = None
    description: str = ""


class ChatRequest(BaseModel):
    session_id: Optional[UUID] = None
    message: str = Field(..., min_length=1, max_length=10000)
    context_alert_id: Optional[UUID] = None
    approve_tool_plan: bool = False
    tool_plan_id: Optional[str] = None
    auto_investigate: bool = False


class ChatResponse(BaseModel):
    session_id: UUID
    message: str
    metadata_json: Optional[dict] = {}
    tool_plan: Optional[dict] = None
