import uuid
import hashlib
from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, Float, ForeignKey, JSON, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


def _make_fingerprint(alertname: str, instance: str | None, labels: dict | None) -> str:
    """Create a stable fingerprint for alert deduplication."""
    key_parts = [alertname or "", instance or ""]
    if labels:
        for k in sorted(labels.keys()):
            if k not in ("severity",):  # severity can change
                key_parts.append(f"{k}={labels[k]}")
    return hashlib.sha256("|".join(key_parts).encode()).hexdigest()[:32]


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alertname: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="firing")  # firing, resolved
    instance: Mapped[str | None] = mapped_column(String(255), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    labels: Mapped[dict] = mapped_column(JSON, default=dict)
    annotations: Mapped[dict] = mapped_column(JSON, default=dict)
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict)
    analysis_status: Mapped[str] = mapped_column(String(50), default="pending")  # pending, analyzing, analyzed, failed
    source: Mapped[str] = mapped_column(String(100), default="prometheus")
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Analysis tracking
    analysis_count: Mapped[int] = mapped_column(Integer, default=0)
    last_analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Deduplication
    fingerprint: Mapped[str] = mapped_column(String(32), nullable=True, index=True)
    dedup_count: Mapped[int] = mapped_column(Integer, default=1)
    # Category auto-tagged from alert labels/name
    alert_category: Mapped[str | None] = mapped_column(String(50), nullable=True, default="general", index=True)
    # Structured metadata extracted by the master agent
    alert_metadata: Mapped[dict] = mapped_column(JSON, default=dict)
    # Name of the agent profile that was matched
    matched_agent_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Acknowledge / close tracking
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    closed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Use DB-level ON DELETE CASCADE and tell SQLAlchemy to be passive
    # so it doesn't try to null-out the child's FK before deleting the parent.
    analysis: Mapped["AlertAnalysis"] = relationship(
        back_populates="alert",
        uselist=False,
        lazy="selectin",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    notes: Mapped[list["AlertNote"]] = relationship(back_populates="alert", order_by="AlertNote.created_at", lazy="selectin", cascade="all, delete-orphan")


class AlertNote(Base):
    __tablename__ = "alert_notes"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alert_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("alerts.id", ondelete="CASCADE"))
    author: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    alert: Mapped["Alert"] = relationship(back_populates="notes")


class AlertAnalysis(Base):
    __tablename__ = "alert_analyses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alert_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("alerts.id", ondelete="CASCADE"), unique=True)
    root_cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    action_plan: Mapped[list] = mapped_column(JSON, default=list)
    fix_commands: Mapped[list] = mapped_column(JSON, default=list)  # structured remediation commands
    prevention_steps: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_level: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ai_provider_used: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ai_model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tools_called: Mapped[list] = mapped_column(JSON, default=list)
    logs_collected: Mapped[dict] = mapped_column(JSON, default=dict)
    full_ai_response: Mapped[dict] = mapped_column(JSON, default=dict)
    analyzed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    alert: Mapped["Alert"] = relationship(back_populates="analysis")
