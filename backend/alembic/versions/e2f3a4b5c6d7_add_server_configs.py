"""add server_configs table

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-04-04 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'e2f3a4b5c6d7'
down_revision: Union[str, None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'server_configs',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('host', sa.String(length=255), nullable=False),
        sa.Column('port', sa.Integer(), nullable=False, server_default='22'),
        sa.Column('username', sa.String(length=100), nullable=False),
        sa.Column('auth_type', sa.String(length=20), nullable=False, server_default='password'),
        sa.Column('ssh_password', sa.Text(), nullable=True),
        sa.Column('ssh_private_key', sa.Text(), nullable=True),
        sa.Column('sudo_enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('sudo_password', sa.Text(), nullable=True),
        sa.Column('os_type', sa.String(length=50), nullable=False, server_default='linux'),
        sa.Column('tags', sa.String(length=255), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('health_status', sa.String(length=50), nullable=False, server_default='unknown'),
        sa.Column('last_health_check', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_index(op.f('ix_server_configs_host'), 'server_configs', ['host'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_server_configs_host'), table_name='server_configs')
    op.drop_table('server_configs')
