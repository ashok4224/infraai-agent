import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, Boolean, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base
from app.core.crypto import EncryptedString


class ServerConfig(Base):
    """SSH-accessible server configuration for OS-level diagnostics."""
    __tablename__ = "server_configs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    host: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    port: Mapped[int] = mapped_column(Integer, nullable=False, default=22)
    username: Mapped[str] = mapped_column(String(100), nullable=False)
    # auth_type: "password" or "key"
    auth_type: Mapped[str] = mapped_column(String(20), nullable=False, default="password")
    ssh_password: Mapped[str | None] = mapped_column(EncryptedString, nullable=True)
    ssh_private_key: Mapped[str | None] = mapped_column(EncryptedString, nullable=True)  # PEM content
    sudo_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sudo_password: Mapped[str | None] = mapped_column(EncryptedString, nullable=True)  # for non-passwordless sudo
    os_type: Mapped[str] = mapped_column(String(50), nullable=False, default="linux")  # linux, windows
    tags: Mapped[str | None] = mapped_column(String(255), nullable=True)  # comma-separated, e.g. "prod,ebs,db"
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    health_status: Mapped[str] = mapped_column(String(50), default="unknown")
    last_health_check: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
