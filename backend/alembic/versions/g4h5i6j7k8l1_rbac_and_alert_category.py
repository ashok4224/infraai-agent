"""rbac tables and alert_category column

Revision ID: g4h5i6j7k8l1
Revises: e2f3a4b5c6d7
Create Date: 2026-04-04 12:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'g4h5i6j7k8l1'
down_revision: Union[str, None] = 'e2f3a4b5c6d7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── alert_category on alerts ───────────────────────────────────────────
    op.add_column('alerts', sa.Column('alert_category', sa.String(length=50), nullable=True, server_default='general'))
    op.create_index(op.f('ix_alerts_alert_category'), 'alerts', ['alert_category'], unique=False)

    # ── Composite index for dedup query (fingerprint + status) ────────────
    op.create_index('ix_alerts_fingerprint_status', 'alerts', ['fingerprint', 'status'], unique=False)

    # ── permissions ────────────────────────────────────────────────────────
    op.create_table(
        'permissions',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('display_name', sa.String(length=200), nullable=False),
        sa.Column('resource', sa.String(length=50), nullable=False),
        sa.Column('action', sa.String(length=50), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_index(op.f('ix_permissions_resource'), 'permissions', ['resource'], unique=False)

    # ── app_roles ──────────────────────────────────────────────────────────
    op.create_table(
        'app_roles',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('display_name', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_system', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )

    # ── role_permissions ───────────────────────────────────────────────────
    op.create_table(
        'role_permissions',
        sa.Column('role_id', sa.UUID(), nullable=False),
        sa.Column('permission_id', sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(['permission_id'], ['permissions.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['role_id'], ['app_roles.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('role_id', 'permission_id'),
    )

    # ── user_roles ────────────────────────────────────────────────────────
    op.create_table(
        'user_roles',
        sa.Column('user_id', sa.UUID(), nullable=False),
        sa.Column('role_id', sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['role_id'], ['app_roles.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'role_id'),
    )


def downgrade() -> None:
    op.drop_table('user_roles')
    op.drop_table('role_permissions')
    op.drop_table('app_roles')
    op.drop_index(op.f('ix_permissions_resource'), table_name='permissions')
    op.drop_table('permissions')
    op.drop_index('ix_alerts_fingerprint_status', table_name='alerts')
    op.drop_index(op.f('ix_alerts_alert_category'), table_name='alerts')
    op.drop_column('alerts', 'alert_category')
