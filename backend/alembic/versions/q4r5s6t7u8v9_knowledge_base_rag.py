"""Add knowledge base tables for RAG (pgvector)

Revision ID: q4r5s6t7u8v9
Revises: p3q4r5s6t7u
Create Date: 2026-04-17 10:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = 'q4r5s6t7u8v9'
down_revision = 'p3q4r5s6t7u'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Install pgvector extension — graceful fail if not available
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── knowledge_sources ──────────────────────────────────────────────
    op.create_table(
        'knowledge_sources',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(200), nullable=False, unique=True),
        sa.Column('description', sa.Text, nullable=True),
        sa.Column('source_type', sa.String(50), nullable=False),  # github, sharepoint, jira, servicenow, upload
        sa.Column('connection_config', sa.JSON, nullable=False, server_default='{}'),
        sa.Column('filter_config', sa.JSON, nullable=False, server_default='{}'),
        sa.Column('sync_interval_hours', sa.Integer, nullable=False, server_default='24'),
        sa.Column('last_synced_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('sync_status', sa.String(50), nullable=False, server_default="'idle'"),
        sa.Column('sync_error', sa.Text, nullable=True),
        sa.Column('is_active', sa.Boolean, nullable=False, server_default='true'),
        sa.Column('doc_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('chunk_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )

    # ── knowledge_documents ────────────────────────────────────────────
    op.create_table(
        'knowledge_documents',
        sa.Column('id', UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('source_id', UUID(as_uuid=True), sa.ForeignKey('knowledge_sources.id', ondelete='CASCADE'), nullable=False),
        sa.Column('title', sa.String(500), nullable=False),
        sa.Column('file_path', sa.String(1000), nullable=True),
        sa.Column('content_hash', sa.String(64), nullable=False),  # SHA-256
        sa.Column('doc_type', sa.String(50), nullable=False, server_default="'text'"),
        sa.Column('raw_size_bytes', sa.Integer, nullable=False, server_default='0'),
        sa.Column('chunk_count', sa.Integer, nullable=False, server_default='0'),
        sa.Column('metadata', sa.JSON, nullable=False, server_default='{}'),
        sa.Column('indexed_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_knowledge_documents_source_id', 'knowledge_documents', ['source_id'])
    op.create_index('ix_knowledge_documents_content_hash', 'knowledge_documents', ['content_hash'])

    # ── knowledge_chunks ───────────────────────────────────────────────
    op.execute("""
        CREATE TABLE knowledge_chunks (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            document_id UUID NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE,
            chunk_index INTEGER NOT NULL DEFAULT 0,
            content TEXT NOT NULL,
            embedding vector(1536),
            token_count INTEGER NOT NULL DEFAULT 0,
            metadata JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.create_index('ix_knowledge_chunks_document_id', 'knowledge_chunks', ['document_id'])
    # IVFFLAT index for fast cosine similarity search
    # The lists parameter should be sqrt(num_rows); 100 is a good default for up to 100K chunks
    op.execute("""
        CREATE INDEX ix_knowledge_chunks_embedding
        ON knowledge_chunks
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
    """)


def downgrade() -> None:
    op.drop_table('knowledge_chunks')
    op.drop_table('knowledge_documents')
    op.drop_table('knowledge_sources')
    op.execute("DROP EXTENSION IF EXISTS vector")
