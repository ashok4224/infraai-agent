"""Add jira_configs table

Revision ID: n1o2p3q4r5s6
Revises: m0n1o2p3q4r5
Create Date: 2026-04-10 00:00:01.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSON

revision = 'n1o2p3q4r5s6'
down_revision = 'm0n1o2p3q4r5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'jira_configs',
        sa.Column('id', UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(100), nullable=False, unique=True),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('instance_type', sa.String(20), nullable=False, server_default='cloud'),
        sa.Column('base_url', sa.String(500), nullable=False),
        sa.Column('auth_email', sa.String(255), nullable=True),
        sa.Column('api_token', sa.Text, nullable=True),  # encrypted via EncryptedString
        sa.Column('project_keys', JSON, nullable=False, server_default='[]'),
        sa.Column('jsm_enabled', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('jsm_service_desk_id', sa.String(50), nullable=True),
        sa.Column('kb_enabled', sa.Boolean, nullable=False, server_default='false'),
        sa.Column('kb_space_keys', JSON, nullable=False, server_default='[]'),
        sa.Column('max_results', sa.Integer, nullable=False, server_default='10'),
        sa.Column('issue_types_filter', JSON, nullable=False, server_default='[]'),
        sa.Column('status_filter', JSON, nullable=False, server_default='[]'),
        sa.Column('label_filter', JSON, nullable=False, server_default='[]'),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('health_status', sa.String(50), nullable=False, server_default="'unknown'"),
        sa.Column('last_health_check', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )


def downgrade() -> None:
    op.drop_table('jira_configs')
