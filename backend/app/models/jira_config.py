import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, Boolean, DateTime, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base
from app.core.crypto import EncryptedString


class JiraConfig(Base):
    __tablename__ = "jira_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    # Jira instance type: "cloud" or "server" (Data Center)
    instance_type: Mapped[str] = mapped_column(String(20), nullable=False, default="cloud")
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)  # e.g. https://yourorg.atlassian.net
    # Authentication: email + API token (cloud) or username + PAT (server/DC)
    auth_email: Mapped[str] = mapped_column(String(255), nullable=True)
    api_token: Mapped[str] = mapped_column(EncryptedString, nullable=True)
    # Project keys to search (comma-separated or JSON list)
    project_keys: Mapped[list] = mapped_column(JSON, default=list)
    # Jira Service Management (JSM) specific
    jsm_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    jsm_service_desk_id: Mapped[str] = mapped_column(String(50), nullable=True)
    # Knowledge Base integration
    kb_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    kb_space_keys: Mapped[list] = mapped_column(JSON, default=list)  # Confluence space keys
    # Search settings
    max_results: Mapped[int] = mapped_column(Integer, default=10)
    issue_types_filter: Mapped[list] = mapped_column(JSON, default=list)  # e.g. ["Bug", "Incident", "Problem"]
    status_filter: Mapped[list] = mapped_column(JSON, default=list)  # e.g. ["Done", "Resolved", "Closed"]
    label_filter: Mapped[list] = mapped_column(JSON, default=list)  # only match issues with these labels
    # Health / status
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    health_status: Mapped[str] = mapped_column(String(50), default="unknown")
    last_health_check: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
