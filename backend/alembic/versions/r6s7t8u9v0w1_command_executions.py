"""Add command_executions table for approval workflow.

Revision ID: r6s7t8u9v0w1
Revises: t3u4v5w6x7y8
Create Date: 2026-04-17
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "r6s7t8u9v0w1"
down_revision = "t3u4v5w6x7y8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "command_executions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("requested_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("requested_by_email", sa.String(255), nullable=False),
        sa.Column("alert_id", UUID(as_uuid=True), sa.ForeignKey("alerts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("chat_session_id", UUID(as_uuid=True), sa.ForeignKey("chat_sessions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("target_type", sa.String(20), nullable=False),
        sa.Column("target_server_id", UUID(as_uuid=True), nullable=True),
        sa.Column("target_server_name", sa.String(255), nullable=True),
        sa.Column("command", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("risk_level", sa.String(20), nullable=False, server_default="Medium"),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("approved_by", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("approved_by_email", sa.String(255), nullable=True),
        sa.Column("approval_note", sa.Text, nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("execution_result", sa.JSON, server_default="{}"),
        sa.Column("execution_duration_ms", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_command_executions_status", "command_executions", ["status"])
    op.create_index("ix_command_executions_requested_by", "command_executions", ["requested_by"])


def downgrade() -> None:
    op.drop_index("ix_command_executions_requested_by")
    op.drop_index("ix_command_executions_status")
    op.drop_table("command_executions")
