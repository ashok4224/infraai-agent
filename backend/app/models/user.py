import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Boolean, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("idp_id", "idp_subject_id", name="uq_users_idp_subject"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(50), default="viewer")  # admin, operator, viewer
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # IDP / SSO fields
    auth_source: Mapped[str] = mapped_column(String(20), default="local")  # local | oidc | saml
    idp_subject_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    idp_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("identity_providers.id", ondelete="SET NULL"), nullable=True)
    role_override: Mapped[bool] = mapped_column(Boolean, default=False)  # True = admin set role, IDP groups won't overwrite
    # MFA
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
