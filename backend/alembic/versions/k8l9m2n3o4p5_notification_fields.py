"""notification fields on mcp_config and agent_profiles

Revision ID: k8l9m2n3o4p5
Revises: j7k8l9m2n3o4
Create Date: 2026-04-05 10:20:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "k8l9m2n3o4p5"
down_revision: Union[str, None] = "j7k8l9m2n3o4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("mcp_server_configs",
                  sa.Column("notification_emails", postgresql.JSON(), server_default="[]", nullable=False))
    op.add_column("mcp_server_configs",
                  sa.Column("notification_cc", postgresql.JSON(), server_default="[]", nullable=False))
    op.add_column("agent_profiles",
                  sa.Column("notification_emails", postgresql.JSON(), server_default="[]", nullable=False))
    op.add_column("agent_profiles",
                  sa.Column("notification_cc", postgresql.JSON(), server_default="[]", nullable=False))


def downgrade() -> None:
    op.drop_column("agent_profiles", "notification_cc")
    op.drop_column("agent_profiles", "notification_emails")
    op.drop_column("mcp_server_configs", "notification_cc")
    op.drop_column("mcp_server_configs", "notification_emails")
