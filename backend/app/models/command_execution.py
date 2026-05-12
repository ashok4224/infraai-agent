"""Command execution model — tracks approval workflow for DB/OS commands."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, DateTime, Boolean, JSON, ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class CommandExecution(Base):
    """Tracks a command that requires approval before execution.

    Lifecycle: pending → approved → executed  (happy path)
               pending → rejected             (admin rejects)
               pending → expired              (TTL timeout)
    """
    __tablename__ = "command_executions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Who / where
    requested_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    requested_by_email: Mapped[str] = mapped_column(String(255), nullable=False)

    # Source context (optional links)
    alert_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("alerts.id", ondelete="SET NULL"), nullable=True)
    chat_session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("chat_sessions.id", ondelete="SET NULL"), nullable=True)

    # Target system
    target_type: Mapped[str] = mapped_column(String(20), nullable=False)  # sql | os | config
    target_server_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)  # MCP or ServerConfig ID
    target_server_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Command details
    command: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False, default="Medium")  # Low|Medium|High|Critical

    # Approval workflow
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")  # pending|approved|rejected|executed|failed|expired
    approved_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_by_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    approval_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Execution result
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    execution_result: Mapped[dict] = mapped_column(JSON, default=dict)  # {success, output, error, duration_ms}
    execution_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # auto-expire pending commands
