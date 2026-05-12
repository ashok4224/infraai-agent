"""Add MFA support: user.mfa_enabled, app_roles.mfa_required, mfa_otp_codes table

Revision ID: s2t3u4v5w6x7
Revises: r1s2t3u4v5w6
Create Date: 2026-04-16 16:00:00.000000
"""
from typing import Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "s2t3u4v5w6x7"
down_revision: Union[str, None] = "r1s2t3u4v5w6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── users.mfa_enabled ─────────────────────────────────────────────────
    op.add_column("users", sa.Column("mfa_enabled", sa.Boolean(), server_default="false", nullable=False))

    # ── app_roles.mfa_required ────────────────────────────────────────────
    op.add_column("app_roles", sa.Column("mfa_required", sa.Boolean(), server_default="false", nullable=False))

    # ── mfa_otp_codes table ───────────────────────────────────────────────
    op.create_table(
        "mfa_otp_codes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("code", sa.String(6), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("mfa_otp_codes")
    op.drop_column("app_roles", "mfa_required")
    op.drop_column("users", "mfa_enabled")
