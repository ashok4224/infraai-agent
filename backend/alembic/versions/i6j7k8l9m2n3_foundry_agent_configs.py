"""foundry agent configs table

Revision ID: i6j7k8l9m2n3
Revises: h5i6j7k8l9m2
Create Date: 2026-04-05 10:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "i6j7k8l9m2n3"
down_revision: Union[str, None] = "h5i6j7k8l9m2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "foundry_agent_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("agent_name", sa.String(100), nullable=False),
        sa.Column("foundry_agent_id", sa.String(255), nullable=True),
        sa.Column("role", sa.String(50), nullable=False),
        sa.Column("system_type", sa.String(50), server_default="all", nullable=False),
        sa.Column("trigger_labels", postgresql.JSON(), server_default="{}", nullable=False),
        sa.Column("pipeline_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_optional", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("config_json", postgresql.JSON(), server_default="{}", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("agent_name"),
    )


def downgrade() -> None:
    op.drop_table("foundry_agent_configs")
