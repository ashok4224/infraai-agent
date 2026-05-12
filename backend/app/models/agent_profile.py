import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, Boolean, DateTime, JSON, Integer
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class AgentProfile(Base):
    __tablename__ = "agent_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    match_keywords: Mapped[list] = mapped_column(JSON, default=list)  # keywords matched against alert labels/name
    match_labels: Mapped[dict] = mapped_column(JSON, default=dict)  # label key-value pairs to match
    priority: Mapped[int] = mapped_column(Integer, default=0)  # higher = checked first
    # agent_type controls which diagnostic pipeline runs for this agent:
    #   "os"       → SSH OS commands only, no MCP/SQL queries
    #   "database" → MCP Oracle SQL queries only
    #   "general"  → hybrid (existing behaviour, keyword-based MCP matching)
    agent_type: Mapped[str] = mapped_column(String(20), nullable=False, default="general")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)  # fallback agent
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    # Per-category notification recipients
    notification_emails: Mapped[list] = mapped_column(JSON, default=list)
    notification_cc: Mapped[list] = mapped_column(JSON, default=list)
