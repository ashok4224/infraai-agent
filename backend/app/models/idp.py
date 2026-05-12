"""Identity Provider and IDP group membership models."""
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Text, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID, JSON
from app.database import Base
from app.core.crypto import EncryptedString


class IdentityProvider(Base):
    __tablename__ = "identity_providers"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    protocol: Mapped[str] = mapped_column(String(10), nullable=False)  # oidc | saml
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    # OIDC fields
    oidc_issuer_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    oidc_client_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    oidc_client_secret: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)
    oidc_scopes: Mapped[str | None] = mapped_column(String(500), nullable=True, default="openid profile email")
    oidc_redirect_uri: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # SAML fields
    saml_entity_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    saml_idp_metadata_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    saml_idp_metadata_xml: Mapped[str | None] = mapped_column(Text, nullable=True)
    saml_acs_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    saml_slo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    saml_certificate: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)

    # Provisioning
    auto_provision: Mapped[bool] = mapped_column(Boolean, default=True)
    default_role: Mapped[str] = mapped_column(String(50), default="viewer")
    group_role_mapping: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    scim_token: Mapped[str | None] = mapped_column(EncryptedString(), nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class UserIdpGroup(Base):
    __tablename__ = "user_idp_groups"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    idp_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("identity_providers.id", ondelete="CASCADE"), nullable=False)
    group_name: Mapped[str] = mapped_column(String(255), nullable=False)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
