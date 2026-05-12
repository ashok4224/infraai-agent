"""Add analysis_count and last_analyzed_at to alerts

Revision ID: p3q4r5s6t7u
Revises: o2p3q4r5s6t
Create Date: 2026-04-16 12:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = 'p3q4r5s6t7u'
down_revision = 'o2p3q4r5s6t'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'alerts',
        sa.Column('analysis_count', sa.Integer(), nullable=False, server_default='0'),
    )
    op.add_column(
        'alerts',
        sa.Column('last_analyzed_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('alerts', 'last_analyzed_at')
    op.drop_column('alerts', 'analysis_count')
