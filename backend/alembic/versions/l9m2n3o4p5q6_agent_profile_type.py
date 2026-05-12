"""Add agent_type to agent_profiles

Revision ID: l9m2n3o4p5q6
Revises: k8l9m2n3o4p5
Create Date: 2026-04-06 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'l9m2n3o4p5q6'
down_revision = 'k8l9m2n3o4p5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'agent_profiles',
        sa.Column('agent_type', sa.String(20), nullable=False, server_default='general'),
    )


def downgrade() -> None:
    op.drop_column('agent_profiles', 'agent_type')
