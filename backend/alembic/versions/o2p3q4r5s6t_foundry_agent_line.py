"""add agent_line to foundry agent configs

Revision ID: o2p3q4r5s6t
Revises: n1o2p3q4r5s6
Create Date: 2026-04-13 22:15:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "o2p3q4r5s6t"
down_revision: Union[str, None] = "n1o2p3q4r5s6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "foundry_agent_configs",
        sa.Column("agent_line", sa.String(length=30), server_default="workflow", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("foundry_agent_configs", "agent_line")
