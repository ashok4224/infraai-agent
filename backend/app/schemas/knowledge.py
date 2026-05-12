from pydantic import BaseModel, Field
from typing import Optional, List, Any
from uuid import UUID
from datetime import datetime


# ── Per-connector filter sub-schemas ────────────────────────────────────

class GitHubFilterConfig(BaseModel):
    repos: List[str] = Field(default_factory=list, description="Repos to index, e.g. ['org/runbooks']")
    branch: str = "main"
    path_includes: List[str] = Field(default_factory=list, description="Only index files under these paths, e.g. ['docs/', 'runbooks/']")
    path_excludes: List[str] = Field(default_factory=list, description="Skip these paths, e.g. ['test/', '.github/']")
    file_extensions: List[str] = Field(default_factory=lambda: [".md", ".txt", ".rst", ".yaml", ".yml", ".json", ".tf", ".hcl", ".properties", ".cfg", ".ini"])
    max_file_size_kb: int = 500
    token: Optional[str] = None  # PAT — encrypted at rest


class SharePointFilterConfig(BaseModel):
    site_ids: List[str] = Field(default_factory=list, description="SharePoint site IDs (empty = use global config)")
    document_libraries: List[str] = Field(default_factory=list, description="Library names, e.g. ['IT Runbooks']")
    folder_paths: List[str] = Field(default_factory=list, description="Folder paths, e.g. ['/Shared Documents/Infra']")
    file_types: List[str] = Field(default_factory=lambda: [".md", ".txt", ".docx", ".pdf"])
    modified_after: Optional[str] = None  # ISO date
    exclude_patterns: List[str] = Field(default_factory=list, description="Filename patterns to skip, e.g. ['Draft*']")


class JiraFilterConfig(BaseModel):
    project_keys: List[str] = Field(default_factory=list)
    issue_types: List[str] = Field(default_factory=lambda: ["Incident", "Problem", "Bug"])
    statuses: List[str] = Field(default_factory=lambda: ["Done", "Resolved", "Closed"])
    labels: List[str] = Field(default_factory=list)
    kb_space_keys: List[str] = Field(default_factory=list)
    updated_after: Optional[str] = None
    max_results: int = 500
    custom_jql: Optional[str] = None


class ServiceNowFilterConfig(BaseModel):
    instance_url: str = ""
    auth_type: str = "basic"  # basic or oauth2
    username: Optional[str] = None
    password: Optional[str] = None  # encrypted at rest
    client_id: Optional[str] = None
    client_secret: Optional[str] = None  # encrypted at rest
    tables: List[str] = Field(default_factory=lambda: ["incident", "problem", "kb_knowledge"])
    assignment_groups: List[str] = Field(default_factory=list)
    ci_classes: List[str] = Field(default_factory=list)
    kb_categories: List[str] = Field(default_factory=list)
    state_filter: List[str] = Field(default_factory=lambda: ["Resolved", "Closed"])
    priority_filter: List[str] = Field(default_factory=list)
    updated_after: Optional[str] = None
    max_results: int = 500
    include_comments: bool = True
    include_resolution: bool = True


class UploadFilterConfig(BaseModel):
    allowed_extensions: List[str] = Field(default_factory=lambda: [".md", ".txt", ".pdf", ".docx", ".yaml", ".json"])
    max_file_size_kb: int = 5000


# ── Source CRUD schemas ─────────────────────────────────────────────────

class KnowledgeSourceCreate(BaseModel):
    name: str
    description: Optional[str] = None
    source_type: str  # github, sharepoint, jira, servicenow, upload
    connection_config: dict = {}
    filter_config: dict = {}
    sync_interval_hours: int = 24
    is_active: bool = True


class KnowledgeSourceUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    connection_config: Optional[dict] = None
    filter_config: Optional[dict] = None
    sync_interval_hours: Optional[int] = None
    is_active: Optional[bool] = None


class KnowledgeSourceResponse(BaseModel):
    id: UUID
    name: str
    description: Optional[str]
    source_type: str
    connection_config: dict
    filter_config: dict
    sync_interval_hours: int
    last_synced_at: Optional[datetime]
    sync_status: str
    sync_error: Optional[str]
    is_active: bool
    doc_count: int
    chunk_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Document schemas ────────────────────────────────────────────────────

class KnowledgeDocumentResponse(BaseModel):
    id: UUID
    source_id: UUID
    title: str
    file_path: Optional[str]
    doc_type: str
    raw_size_bytes: int
    chunk_count: int
    doc_metadata: dict
    indexed_at: datetime

    model_config = {"from_attributes": True}


# ── Search schemas ──────────────────────────────────────────────────────

class KnowledgeSearchRequest(BaseModel):
    query: str
    top_k: int = 5
    source_types: Optional[List[str]] = None
    source_ids: Optional[List[UUID]] = None
    score_threshold: float = 0.7


class KnowledgeSearchResult(BaseModel):
    chunk_content: str
    score: float
    document_title: str
    source_name: str
    source_type: str
    file_path: Optional[str] = None
    doc_metadata: dict = {}


class KnowledgeSearchResponse(BaseModel):
    results: List[KnowledgeSearchResult]
    query: str
    total: int


# ── Sync schemas ────────────────────────────────────────────────────────

class SyncStatusResponse(BaseModel):
    source_id: UUID
    sync_status: str
    last_synced_at: Optional[datetime]
    doc_count: int
    chunk_count: int
    sync_error: Optional[str]


class SyncPreviewResponse(BaseModel):
    estimated_documents: int
    estimated_chunks: int
    estimated_tokens: int
    estimated_cost_usd: float
    source_type: str
    filters_applied: dict


# ── RAG settings schema ────────────────────────────────────────────────

class RAGSettingsResponse(BaseModel):
    rag_enabled: bool
    rag_embedding_model: str
    rag_chunk_size: int
    rag_chunk_overlap: int
    rag_top_k: int
    rag_score_threshold: float
