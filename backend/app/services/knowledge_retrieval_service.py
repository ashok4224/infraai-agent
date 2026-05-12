"""RAG retrieval service — vector similarity search against the knowledge base."""
import logging
from typing import List, Optional
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.services.rag_utils import is_rag_enabled, get_rag_settings
from app.services.embedding_service import embed_text

logger = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    chunk_content: str
    score: float
    document_title: str
    source_name: str
    source_type: str
    file_path: str = ""
    metadata: dict = field(default_factory=dict)


async def search_knowledge_base(
    query: str,
    db: AsyncSession,
    *,
    top_k: int | None = None,
    score_threshold: float | None = None,
    source_types: list[str] | None = None,
    source_ids: list[str] | None = None,
) -> List[RetrievedChunk]:
    """Search the knowledge base using the query string. Returns ranked chunks."""
    if not await is_rag_enabled(db):
        return []

    settings = await get_rag_settings(db)
    if top_k is None:
        top_k = int(settings.get("rag_top_k", 5))
    if score_threshold is None:
        score_threshold = float(settings.get("rag_score_threshold", 0.7))

    try:
        query_embedding = await embed_text(query, db)
    except Exception as e:
        logger.error("Failed to embed search query: %s", e)
        return []

    # Build pgvector cosine similarity query
    embedding_literal = "[" + ",".join(str(v) for v in query_embedding) + "]"

    where_clauses = ["ks.is_active = true"]
    params = {}
    if source_types:
        where_clauses.append("ks.source_type = ANY(:source_types)")
        params["source_types"] = source_types
    if source_ids:
        where_clauses.append("ks.id = ANY(:source_ids::uuid[])")
        params["source_ids"] = source_ids

    where_sql = " AND ".join(where_clauses)

    sql = text(f"""
        SELECT
            kc.content,
            1 - (kc.embedding <=> :embedding::vector) AS score,
            kd.title AS doc_title,
            ks.name AS source_name,
            ks.source_type,
            kd.file_path,
            kc.metadata AS chunk_metadata,
            kd.metadata AS doc_metadata
        FROM knowledge_chunks kc
        JOIN knowledge_documents kd ON kd.id = kc.document_id
        JOIN knowledge_sources ks ON ks.id = kd.source_id
        WHERE {where_sql}
          AND 1 - (kc.embedding <=> :embedding::vector) >= :threshold
        ORDER BY kc.embedding <=> :embedding::vector
        LIMIT :top_k
    """)

    params.update({
        "embedding": embedding_literal,
        "threshold": score_threshold,
        "top_k": top_k,
    })

    result = await db.execute(sql, params)
    rows = result.fetchall()

    chunks = []
    for row in rows:
        chunks.append(RetrievedChunk(
            chunk_content=row[0],
            score=float(row[1]),
            document_title=row[2],
            source_name=row[3],
            source_type=row[4],
            file_path=row[5] or "",
            metadata={**(row[6] or {}), **(row[7] or {})},
        ))

    logger.info("RAG search returned %d chunks (query: %.50s…)", len(chunks), query)
    return chunks


async def get_context_for_alert(
    alert_name: str,
    alert_description: str,
    db: AsyncSession,
    labels: dict | None = None,
) -> str:
    """Build a RAG context block for an alert. Returns formatted string or empty."""
    if not await is_rag_enabled(db):
        return ""

    query_parts = [alert_name]
    if alert_description:
        query_parts.append(alert_description)
    if labels:
        for key in ("severity", "instance", "job", "service", "namespace"):
            if key in labels:
                query_parts.append(f"{key}={labels[key]}")

    query = " ".join(query_parts)
    chunks = await search_knowledge_base(query, db)
    if not chunks:
        return ""

    context_lines = ["## Relevant Knowledge Base Context\n"]
    for i, chunk in enumerate(chunks, 1):
        context_lines.append(
            f"### [{i}] {chunk.source_name} — {chunk.document_title} (score: {chunk.score:.2f})\n"
            f"Source: {chunk.source_type} | File: {chunk.file_path}\n\n"
            f"{chunk.chunk_content}\n"
        )
    return "\n".join(context_lines)


async def get_context_for_chat(
    message: str,
    db: AsyncSession,
) -> str:
    """Build a RAG context block for a chat query. Returns formatted string or empty."""
    if not await is_rag_enabled(db):
        return ""

    chunks = await search_knowledge_base(message, db)
    if not chunks:
        return ""

    context_lines = ["The following context from the knowledge base may be relevant:\n"]
    for i, chunk in enumerate(chunks, 1):
        context_lines.append(
            f"[{i}] **{chunk.document_title}** ({chunk.source_name})\n"
            f"{chunk.chunk_content}\n"
        )
    return "\n".join(context_lines)
