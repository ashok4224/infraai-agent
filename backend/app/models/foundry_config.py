import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, Boolean, DateTime, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class FoundryAgentConfig(Base):
    __tablename__ = "foundry_agent_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    foundry_agent_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    agent_line: Mapped[str] = mapped_column(String(30), default="workflow")  # workflow | technology
    role: Mapped[str] = mapped_column(String(50), nullable=False)  # researcher | collector | solver | notifier | knowledge | chat
    system_type: Mapped[str] = mapped_column(String(50), default="all")  # oracle | postgresql | mongodb | aws | all
    trigger_labels: Mapped[dict] = mapped_column(JSON, default=dict)  # label matchers for activation
    pipeline_order: Mapped[int] = mapped_column(Integer, default=0)  # execution sequence
    is_optional: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    config_json: Mapped[dict] = mapped_column(JSON, default=dict)  # agent-specific settings
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
