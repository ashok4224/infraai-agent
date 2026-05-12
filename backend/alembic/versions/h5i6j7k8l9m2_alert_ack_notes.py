"""alert acknowledge, close-by, and notes table

Revision ID: h5i6j7k8l9m2
Revises: g4h5i6j7k8l1
Create Date: 2026-04-04 18:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'h5i6j7k8l9m2'
down_revision: Union[str, None] = 'g4h5i6j7k8l1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # New columns on alerts table
    op.add_column('alerts', sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('alerts', sa.Column('acknowledged_by', sa.String(length=255), nullable=True))
    op.add_column('alerts', sa.Column('closed_by', sa.String(length=255), nullable=True))

    # Alert notes table
    op.create_table(
        'alert_notes',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('alert_id', sa.UUID(), nullable=False),
        sa.Column('author', sa.String(length=255), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False,
                   server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['alert_id'], ['alerts.id'], ondelete='CASCADE'),
    )
    op.create_index('ix_alert_notes_alert_id', 'alert_notes', ['alert_id'])

    # Update alert_analyses FK to cascade on delete (drop and recreate)
    op.drop_constraint('alert_analyses_alert_id_fkey', 'alert_analyses', type_='foreignkey')
    op.create_foreign_key(
        'alert_analyses_alert_id_fkey', 'alert_analyses', 'alerts',
        ['alert_id'], ['id'], ondelete='CASCADE',
    )


def downgrade() -> None:
    op.drop_constraint('alert_analyses_alert_id_fkey', 'alert_analyses', type_='foreignkey')
    op.create_foreign_key(
        'alert_analyses_alert_id_fkey', 'alert_analyses', 'alerts',
        ['alert_id'], ['id'],
    )
    op.drop_index('ix_alert_notes_alert_id', table_name='alert_notes')
    op.drop_table('alert_notes')
    op.drop_column('alerts', 'closed_by')
    op.drop_column('alerts', 'acknowledged_by')
    op.drop_column('alerts', 'acknowledged_at')
