import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, Boolean, DateTime, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base
from app.core.crypto import EncryptedString


class MCPServerConfig(Base):
    __tablename__ = "mcp_server_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    server_type: Mapped[str] = mapped_column(String(50), nullable=False, default="sqlcl")  # sqlcl, custom
    command: Mapped[str] = mapped_column(Text, nullable=False)  # e.g., "sql" for SQLcl
    args: Mapped[list] = mapped_column(JSON, default=list)  # command arguments
    env_vars: Mapped[dict] = mapped_column(JSON, default=dict)  # environment variables for the MCP server
    connection_string: Mapped[str] = mapped_column(Text, nullable=True)  # Oracle connection string
    oracle_host: Mapped[str] = mapped_column(String(255), nullable=True)
    oracle_port: Mapped[int] = mapped_column(Integer, nullable=True, default=1521)
    oracle_service: Mapped[str] = mapped_column(String(255), nullable=True)
    oracle_user: Mapped[str] = mapped_column(String(255), nullable=True)
    oracle_password: Mapped[str] = mapped_column(EncryptedString, nullable=True)  # encrypted in production
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    tools_available: Mapped[list] = mapped_column(JSON, default=list)  # list of MCP tools exposed
    health_status: Mapped[str] = mapped_column(String(50), default="unknown")  # healthy, unhealthy, unknown
    last_health_check: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    # Per-database notification recipients
    notification_emails: Mapped[list] = mapped_column(JSON, default=list)
    notification_cc: Mapped[list] = mapped_column(JSON, default=list)
