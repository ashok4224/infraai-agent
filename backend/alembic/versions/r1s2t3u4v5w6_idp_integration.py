"""Add identity_providers, user IDP fields, and user_idp_groups

Revision ID: r1s2t3u4v5w6
Revises: q5r6s7t8u9v0
Create Date: 2026-04-16 14:00:00.000000
"""
from typing import Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSON

revision = "r1s2t3u4v5w6"
down_revision: Union[str, None] = "q5r6s7t8u9v0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── identity_providers table ──────────────────────────────────────────
    op.create_table(
        "identity_providers",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.String(100), unique=True, nullable=False),
        sa.Column("protocol", sa.String(10), nullable=False),  # oidc | saml
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("is_default", sa.Boolean(), server_default="false", nullable=False),
        # OIDC
        sa.Column("oidc_issuer_url", sa.String(500), nullable=True),
        sa.Column("oidc_client_id", sa.String(255), nullable=True),
        sa.Column("oidc_client_secret", sa.Text(), nullable=True),  # encrypted
        sa.Column("oidc_scopes", sa.String(500), nullable=True, server_default="openid profile email"),
        sa.Column("oidc_redirect_uri", sa.String(500), nullable=True),
        # SAML
        sa.Column("saml_entity_id", sa.String(500), nullable=True),
        sa.Column("saml_idp_metadata_url", sa.String(500), nullable=True),
        sa.Column("saml_idp_metadata_xml", sa.Text(), nullable=True),
        sa.Column("saml_acs_url", sa.String(500), nullable=True),
        sa.Column("saml_slo_url", sa.String(500), nullable=True),
        sa.Column("saml_certificate", sa.Text(), nullable=True),  # encrypted
        # Provisioning
        sa.Column("auto_provision", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("default_role", sa.String(50), server_default="viewer", nullable=False),
        sa.Column("group_role_mapping", JSON(), nullable=True),  # {"IDP-Group": "admin", ...}
        sa.Column("scim_token", sa.Text(), nullable=True),  # encrypted bearer token for SCIM
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # ── Extend users table ────────────────────────────────────────────────
    op.add_column("users", sa.Column("auth_source", sa.String(20), server_default="local", nullable=False))
    op.add_column("users", sa.Column("idp_subject_id", sa.String(512), nullable=True))
    op.add_column("users", sa.Column("idp_id", UUID(as_uuid=True), nullable=True))
    op.add_column("users", sa.Column("role_override", sa.Boolean(), server_default="false", nullable=False))

    op.create_foreign_key(
        "fk_users_idp_id",
        "users",
        "identity_providers",
        ["idp_id"],
        ["id"],
        ondelete="SET NULL",
    )
    # Unique constraint: one subject ID per IDP
    op.create_unique_constraint("uq_users_idp_subject", "users", ["idp_id", "idp_subject_id"])

    # Make hashed_password nullable (IDP users have no local password)
    op.alter_column("users", "hashed_password", existing_type=sa.String(255), nullable=True)

    # ── user_idp_groups table ─────────────────────────────────────────────
    op.create_table(
        "user_idp_groups",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("idp_id", UUID(as_uuid=True), sa.ForeignKey("identity_providers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("group_name", sa.String(255), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_user_idp_groups_user", "user_idp_groups", ["user_id"])


def downgrade() -> None:
    op.drop_table("user_idp_groups")
    op.drop_constraint("uq_users_idp_subject", "users", type_="unique")
    op.drop_constraint("fk_users_idp_id", "users", type_="foreignkey")
    op.alter_column("users", "hashed_password", existing_type=sa.String(255), nullable=False)
    op.drop_column("users", "role_override")
    op.drop_column("users", "idp_id")
    op.drop_column("users", "idp_subject_id")
    op.drop_column("users", "auth_source")
    op.drop_table("identity_providers")
