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


async def _search_foundry_vector_store(
    query: str,
    top_k: int,
    source_types: list[str] | None = None,
    source_ids: list[str] | None = None,
) -> List[RetrievedChunk]:
    """Search Azure AI Foundry knowledge via the infraai-knowledge agent.

    Uses the Foundry Assistants Threads API to run a short search query
    through the infraai-knowledge agent, which is connected to the vector
    store via file_search tool.  The agent returns the most relevant
    snippets from the indexed documents.
    """
    import asyncio
    import httpx
    from app.services.azure_foundry_service import (
        _threads_base, _THREADS_API_VERSION, _threads_headers,
        _ensure_assistant_id,
    )
    from app.config import settings as app_settings

    if not app_settings.AZURE_AI_FOUNDRY_ENDPOINT:
        return []

    agent_name = "infraai-knowledge"
    assistant_id = await _ensure_assistant_id(agent_name)
    if not assistant_id:
        logger.debug("Agent '%s' not found in Foundry — cannot search via agent", agent_name)
        return []

    base = _threads_base()
    ver = _THREADS_API_VERSION
    hdrs = _threads_headers()

    # Prompt the agent to search and return relevant file snippets
    search_message = (
        f"Search your knowledge base for information about: {query}\n\n"
        f"Return the top {top_k} most relevant document snippets with their "
        f"file names and relevance scores. Format each result as: "
        f"FILE: <filename> | SCORE: <0.0-1.0> | CONTENT: <snippet>"
    )

    try:
        async with httpx.AsyncClient(timeout=60.0) as http:
            # 1. Create thread
            r = await http.post(f"{base}/threads?api-version={ver}", headers=hdrs, json={})
            r.raise_for_status()
            thread_id = r.json()["id"]

            try:
                # 2. Add search message
                r = await http.post(
                    f"{base}/threads/{thread_id}/messages?api-version={ver}",
                    headers=hdrs,
                    json={"role": "user", "content": search_message},
                )
                r.raise_for_status()

                # 3. Create run
                r = await http.post(
                    f"{base}/threads/{thread_id}/runs?api-version={ver}",
                    headers=hdrs,
                    json={"assistant_id": assistant_id},
                )
                r.raise_for_status()
                run_id = r.json()["id"]

                # 4. Poll (shorter timeout for search)
                elapsed = 0.0
                poll = 1.0
                while elapsed < 45.0:
                    await asyncio.sleep(poll)
                    elapsed += poll
                    poll = min(poll * 1.5, 5.0)
                    r = await http.get(
                        f"{base}/threads/{thread_id}/runs/{run_id}?api-version={ver}",
                        headers=hdrs,
                    )
                    r.raise_for_status()
                    status = r.json().get("status", "")
                    if status == "completed":
                        break
                    if status in ("failed", "cancelled", "expired"):
                        raise RuntimeError(f"Agent run {status}")

                # 5. Get assistant reply
                r = await http.get(
                    f"{base}/threads/{thread_id}/messages?api-version={ver}&order=desc&limit=5",
                    headers=hdrs,
                )
                r.raise_for_status()
                reply = ""
                for msg in r.json().get("data", []):
                    if msg.get("role") == "assistant":
                        for block in msg.get("content", []):
                            if block.get("type") == "text":
                                reply = block["text"]["value"]
                                break
                        break
            finally:
                # Cleanup thread
                try:
                    await http.delete(f"{base}/threads/{thread_id}?api-version={ver}", headers=hdrs)
                except Exception:
                    pass

    except Exception as e:
        logger.warning("Foundry agent search failed: %s", e)
        return []

    # Parse the agent's structured response
    if not reply:
        return []

    chunks = []
    import re
    for match in re.finditer(
        r"FILE:\s*(.+?)\s*\|\s*SCORE:\s*([0-9.]+)\s*\|\s*CONTENT:\s*(.+?)(?=FILE:|$)",
        reply, re.DOTALL | re.IGNORECASE
    ):
        fname = match.group(1).strip()
        try:
            score = float(match.group(2))
        except ValueError:
            score = 0.5
        content = match.group(3).strip()[:2000]
        chunks.append(RetrievedChunk(
            chunk_content=content,
            score=min(score, 1.0),
            document_title=fname,
            source_name="azure_foundry",
            source_type="foundry",
            file_path=fname,
            metadata={"source": "foundry_agent_search", "agent": agent_name},
        ))

    # Fallback: if agent didn't format results, treat whole reply as one chunk
    if not chunks and reply:
        chunks.append(RetrievedChunk(
            chunk_content=reply[:2000],
            score=0.5,
            document_title="Foundry Knowledge",
            source_name="azure_foundry",
            source_type="foundry",
            file_path="",
            metadata={"source": "foundry_agent_search", "unstructured": True},
        ))

    logger.info("Foundry agent search returned %d chunks for: %.50s…", len(chunks), query)
    return chunks


async def search_knowledge_base(
    query: str,
    db: AsyncSession,
    *,
    top_k: int | None = None,
    score_threshold: float | None = None,
    source_types: list[str] | None = None,
    source_ids: list[str] | None = None,
) -> List[RetrievedChunk]:
    """Search the knowledge base using the query string. Returns ranked chunks.
    
    Prefers Azure AI Foundry vector store when available (auto-chunked + auto-embedded).
    Falls back to local pgvector when Foundry is not configured.
    """
    if not await is_rag_enabled(db):
        return []

    settings = await get_rag_settings(db)
    if top_k is None:
        top_k = int(settings.get("rag_top_k", 5))
    if score_threshold is None:
        score_threshold = float(settings.get("rag_score_threshold", 0.7))

    from app.config import settings as app_settings

    # ── Primary path: Foundry vector store (fully managed, no local embed needed) ──
    if app_settings.AZURE_AI_FOUNDRY_ENDPOINT:
        foundry_chunks = await _search_foundry_vector_store(query, top_k, source_types, source_ids)
        if foundry_chunks:
            return foundry_chunks[:top_k]
        # Fall through to pgvector if Foundry returns nothing

    # ── Fallback: local pgvector (requires embedding provider) ──
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
