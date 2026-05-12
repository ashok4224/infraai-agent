"""Add alert_metadata and matched_agent_name to alerts

Revision ID: m0n1o2p3q4r5
Revises: l9m2n3o4p5q6
Create Date: 2026-04-06 00:00:01.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON

revision = 'm0n1o2p3q4r5'
down_revision = 'l9m2n3o4p5q6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'alerts',
        sa.Column('alert_metadata', JSON, nullable=False, server_default='{}'),
    )
    op.add_column(
        'alerts',
        sa.Column('matched_agent_name', sa.String(200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('alerts', 'matched_agent_name')
    op.drop_column('alerts', 'alert_metadata')
