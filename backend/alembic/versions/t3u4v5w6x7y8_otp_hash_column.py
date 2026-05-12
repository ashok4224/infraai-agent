"""Widen OTP code column for HMAC-SHA256 hashes.

Revision ID: t3u4v5w6x7y8
Revises: s2t3u4v5w6x7
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa

revision = "t3u4v5w6x7y8"
down_revision = "s2t3u4v5w6x7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "mfa_otp_codes",
        "code",
        existing_type=sa.String(6),
        type_=sa.String(128),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "mfa_otp_codes",
        "code",
        existing_type=sa.String(128),
        type_=sa.String(6),
        existing_nullable=False,
    )
