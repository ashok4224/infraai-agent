"""Fine-grained RBAC: permissions → roles → users."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, Boolean, DateTime, Table, Column, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base

# ── Association tables ─────────────────────────────────────────────────────

role_permissions = Table(
    "role_permissions",
    Base.metadata,
    Column("role_id", UUID(as_uuid=True), ForeignKey("app_roles.id", ondelete="CASCADE"), primary_key=True),
    Column("permission_id", UUID(as_uuid=True), ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
)

user_roles = Table(
    "user_roles",
    Base.metadata,
    Column("user_id", UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("role_id", UUID(as_uuid=True), ForeignKey("app_roles.id", ondelete="CASCADE"), primary_key=True),
)


class Permission(Base):
    """Atomic permission — resource + action pair."""
    __tablename__ = "permissions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)          # "alerts:view"
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    resource: Mapped[str] = mapped_column(String(50), nullable=False, index=True)        # "alerts"
    action: Mapped[str] = mapped_column(String(50), nullable=False)                      # "view"
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class AppRole(Base):
    """Custom role composed of permissions."""
    __tablename__ = "app_roles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)   # built-in; cannot be deleted/renamed
    mfa_required: Mapped[bool] = mapped_column(Boolean, default=False)  # enforce MFA for all users with this role
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    permissions: Mapped[list["Permission"]] = relationship(secondary=role_permissions, lazy="selectin")
