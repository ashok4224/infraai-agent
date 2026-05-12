from pydantic import BaseModel, model_validator, Field
from typing import Optional, List, Any
from uuid import UUID
from datetime import datetime


class AlertWebhookPayload(BaseModel):
    status: str
    alerts: List[dict]
    groupLabels: Optional[dict] = None
    commonLabels: Optional[dict] = None
    commonAnnotations: Optional[dict] = None
    externalURL: Optional[str] = None


class AlertResponse(BaseModel):
    id: UUID
    alertname: str
    severity: str
    status: str
    instance: Optional[str]
    summary: Optional[str]
    description: Optional[str]
    labels: dict
    annotations: dict
    analysis_status: str
    source: str
    alert_category: Optional[str] = "general"
    alert_metadata: dict = {}
    matched_agent_name: Optional[str] = None
    received_at: datetime
    resolved_at: Optional[datetime]
    acknowledged_at: Optional[datetime] = None
    acknowledged_by: Optional[str] = None
    closed_by: Optional[str] = None
    dedup_count: int = 1
    analysis_count: int = 0
    last_analyzed_at: Optional[datetime] = None
    analysis: Optional["AlertAnalysisResponse"] = None
    notes: List["AlertNoteResponse"] = []

    model_config = {"from_attributes": True}


class AlertAnalysisResponse(BaseModel):
    id: UUID
    alert_id: UUID
    problem_statement: Optional[str] = None
    root_cause: Optional[str]
    confidence_score: Optional[float]
    action_plan: list
    fix_commands: list = []
    prevention_steps: Optional[str]
    risk_level: Optional[str]
    ai_provider_used: Optional[str]
    ai_model_used: Optional[str]
    tools_called: list
    logs_collected: dict
    full_ai_response: dict = {}
    analyzed_at: datetime

    model_config = {"from_attributes": True}

    @model_validator(mode='after')
    def _pull_problem_statement(self) -> 'AlertAnalysisResponse':
        """Back-fill problem_statement from full_ai_response for analyses that have it."""
        if not self.problem_statement and isinstance(self.full_ai_response, dict):
            self.problem_statement = self.full_ai_response.get('problem_statement')
        return self


class AlertListResponse(BaseModel):
    alerts: List[AlertResponse]
    total: int
    page: int
    per_page: int


class ManualAlertCreate(BaseModel):
    alertname: str
    severity: str = "warning"
    instance: Optional[str] = None
    summary: Optional[str] = None
    description: Optional[str] = None
    labels: dict = {}
    source: str = "manual"


class AlertNoteResponse(BaseModel):
    id: UUID
    alert_id: UUID
    author: str
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class AlertNoteCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=5000)


class BulkAlertAction(BaseModel):
    alert_ids: List[UUID]

