"""phase1 updates

Revision ID: d1e2f3a4b5c6
Revises: c08d45cea8c9
Create Date: 2026-04-03 15:15:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, None] = 'c08d45cea8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new fields for alert deduplication
    op.add_column('alerts', sa.Column('fingerprint', sa.String(length=32), nullable=True))
    op.add_column('alerts', sa.Column('dedup_count', sa.Integer(), server_default='1', nullable=False))
    op.create_index(op.f('ix_alerts_fingerprint'), 'alerts', ['fingerprint'], unique=False)
    
    # Add fix_commands for remediation payload
    op.add_column('alert_analyses', sa.Column('fix_commands', sa.JSON(), server_default='[]', nullable=False))


def downgrade() -> None:
    op.drop_column('alert_analyses', 'fix_commands')
    op.drop_index(op.f('ix_alerts_fingerprint'), table_name='alerts')
    op.drop_column('alerts', 'dedup_count')
    op.drop_column('alerts', 'fingerprint')
