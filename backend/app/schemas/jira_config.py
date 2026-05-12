from pydantic import BaseModel
from typing import Optional, List
from uuid import UUID
from datetime import datetime


class JiraConfigCreate(BaseModel):
    name: str
    description: Optional[str] = None
    instance_type: str = "cloud"
    base_url: str
    auth_email: Optional[str] = None
    api_token: Optional[str] = None
    project_keys: List[str] = []
    jsm_enabled: bool = False
    jsm_service_desk_id: Optional[str] = None
    kb_enabled: bool = False
    kb_space_keys: List[str] = []
    max_results: int = 10
    issue_types_filter: List[str] = []
    status_filter: List[str] = []
    label_filter: List[str] = []
    is_active: bool = True


class JiraConfigUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    instance_type: Optional[str] = None
    base_url: Optional[str] = None
    auth_email: Optional[str] = None
    api_token: Optional[str] = None
    project_keys: Optional[List[str]] = None
    jsm_enabled: Optional[bool] = None
    jsm_service_desk_id: Optional[str] = None
    kb_enabled: Optional[bool] = None
    kb_space_keys: Optional[List[str]] = None
    max_results: Optional[int] = None
    issue_types_filter: Optional[List[str]] = None
    status_filter: Optional[List[str]] = None
    label_filter: Optional[List[str]] = None
    is_active: Optional[bool] = None


class JiraConfigResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    instance_type: str
    base_url: str
    auth_email: Optional[str]
    has_token: bool = False
    project_keys: List[str]
    jsm_enabled: bool
    jsm_service_desk_id: Optional[str]
    kb_enabled: bool
    kb_space_keys: List[str]
    max_results: int
    issue_types_filter: List[str]
    status_filter: List[str]
    label_filter: List[str]
    is_active: bool
    health_status: str
    last_health_check: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class JiraSearchRequest(BaseModel):
    """Manual Jira search from the UI."""
    config_id: UUID
    query: str
    max_results: int = 10


class JiraIssueResponse(BaseModel):
    key: str
    summary: str
    status: str
    issue_type: str
    priority: Optional[str] = None
    resolution: Optional[str] = None
    description_snippet: Optional[str] = None
    labels: List[str] = []
    created: Optional[str] = None
    updated: Optional[str] = None
    url: str


class JiraSearchResponse(BaseModel):
    total: int
    issues: List[JiraIssueResponse]
