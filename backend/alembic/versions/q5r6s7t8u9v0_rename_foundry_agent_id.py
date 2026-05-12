"""Rename foundry_agent_id to foundry_agent_name.

Revision ID: q5r6s7t8u9v0
Revises: q4r5s6t7u8v9
Create Date: 2026-04-16 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "q5r6s7t8u9v0"
down_revision: Union[str, None] = "q4r5s6t7u8v9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "foundry_agent_configs",
        "foundry_agent_id",
        new_column_name="foundry_agent_name",
    )


def downgrade() -> None:
    op.alter_column(
        "foundry_agent_configs",
        "foundry_agent_name",
        new_column_name="foundry_agent_id",
    )