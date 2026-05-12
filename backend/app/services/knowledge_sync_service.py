"""Knowledge sync service — orchestrates fetch → chunk → embed → store pipeline."""
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, delete, func

from app.models.knowledge import KnowledgeSource, KnowledgeDocument, KnowledgeChunk
from app.services.knowledge_connectors import get_connector, RawDocument
from app.services.chunker_service import chunk_document
from app.services.embedding_service import embed_batch
from app.services.rag_utils import is_rag_enabled, get_rag_settings

logger = logging.getLogger(__name__)

# Max chunks per embed_batch call to stay within API limits
_EMBED_BATCH_SIZE = 50


async def sync_source(source_id: str, db: AsyncSession, *, force: bool = False) -> dict:
    """Run a full sync for a knowledge source: fetch → chunk → embed → store.

    Returns sync result dict with counts.
    """
    if not await is_rag_enabled(db):
        return {"status": "skipped", "reason": "RAG is disabled"}

    result = await db.execute(
        select(KnowledgeSource).where(KnowledgeSource.id == source_id)
    )
    source = result.scalars().first()
    if not source:
        return {"status": "error", "reason": "Source not found"}

    if source.sync_status == "running" and not force:
        return {"status": "skipped", "reason": "Sync already running"}

    # Mark running
    source.sync_status = "running"
    source.sync_error = None
    await db.commit()

    stats = {"docs_fetched": 0, "docs_new": 0, "docs_updated": 0, "docs_unchanged": 0,
             "chunks_created": 0, "errors": []}

    try:
        connector = get_connector(source.source_type)
        raw_docs = await connector.fetch_documents(
            source.connection_config or {},
            source.filter_config or {},
        )
        stats["docs_fetched"] = len(raw_docs)

        rag_settings = await get_rag_settings(db)
        chunk_size = int(rag_settings.get("rag_chunk_size", 500))
        chunk_overlap = int(rag_settings.get("rag_chunk_overlap", 50))

        # Get existing document hashes for delta detection
        existing_docs = await db.execute(
            select(KnowledgeDocument.id, KnowledgeDocument.content_hash, KnowledgeDocument.file_path)
            .where(KnowledgeDocument.source_id == source.id)
        )
        existing_map = {row[2]: (row[0], row[1]) for row in existing_docs.fetchall()}
        seen_paths = set()

        for raw_doc in raw_docs:
            path = raw_doc.file_path
            seen_paths.add(path)
            content_hash = raw_doc.content_hash

            if path in existing_map:
                doc_id, old_hash = existing_map[path]
                if old_hash == content_hash:
                    stats["docs_unchanged"] += 1
                    continue
                # Updated document — delete old chunks and re-index
                await db.execute(
                    delete(KnowledgeChunk).where(KnowledgeChunk.document_id == doc_id)
                )
                doc_result = await db.execute(
                    select(KnowledgeDocument).where(KnowledgeDocument.id == doc_id)
                )
                doc = doc_result.scalars().first()
                if doc:
                    doc.content_hash = content_hash
                    doc.raw_size_bytes = raw_doc.raw_size_bytes
                    doc.indexed_at = datetime.now(timezone.utc)
                stats["docs_updated"] += 1
            else:
                # New document
                doc = KnowledgeDocument(
                    source_id=source.id,
                    title=raw_doc.title,
                    file_path=path,
                    content_hash=content_hash,
                    doc_type=raw_doc.doc_type,
                    raw_size_bytes=raw_doc.raw_size_bytes,
                    doc_metadata=raw_doc.metadata,
                )
                db.add(doc)
                await db.flush()
                doc_id = doc.id
                stats["docs_new"] += 1

            # Chunk the document
            try:
                chunks = chunk_document(
                    raw_doc.content,
                    raw_doc.doc_type,
                    chunk_size=chunk_size,
                    chunk_overlap=chunk_overlap,
                    file_path=raw_doc.file_path,
                )
            except Exception as e:
                stats["errors"].append(f"Chunk error for {path}: {e}")
                continue

            # Embed in batches
            chunk_texts = [c.content for c in chunks]
            all_embeddings = []
            for i in range(0, len(chunk_texts), _EMBED_BATCH_SIZE):
                batch = chunk_texts[i:i + _EMBED_BATCH_SIZE]
                try:
                    batch_embeddings = await embed_batch(batch, db)
                    all_embeddings.extend(batch_embeddings)
                except Exception as e:
                    stats["errors"].append(f"Embed error for {path} batch {i}: {e}")
                    break

            if len(all_embeddings) != len(chunks):
                stats["errors"].append(f"Embedding count mismatch for {path}")
                continue

            # Store chunks with embeddings
            for idx, (chunk, embedding) in enumerate(zip(chunks, all_embeddings)):
                chunk_id = uuid.uuid4()
                embedding_literal = "[" + ",".join(str(v) for v in embedding) + "]"
                await db.execute(text("""
                    INSERT INTO knowledge_chunks (id, document_id, chunk_index, content, embedding, token_count, metadata, created_at)
                    VALUES (:id, :doc_id, :idx, :content, :embedding::vector, :tokens, :meta::jsonb, NOW())
                """), {
                    "id": str(chunk_id),
                    "doc_id": str(doc_id),
                    "idx": idx,
                    "content": chunk.content,
                    "embedding": embedding_literal,
                    "tokens": chunk.token_count,
                    "meta": str(chunk.metadata).replace("'", '"') if chunk.metadata else "{}",
                })
                stats["chunks_created"] += 1

            # Update document chunk count
            if doc:
                doc.chunk_count = len(chunks)

        # Remove documents that no longer exist in the source
        deleted_paths = set(existing_map.keys()) - seen_paths
        if deleted_paths:
            for dpath in deleted_paths:
                doc_id, _ = existing_map[dpath]
                await db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == doc_id))
                await db.execute(delete(KnowledgeDocument).where(KnowledgeDocument.id == doc_id))

        # Update source stats
        doc_count = await db.execute(
            select(func.count()).select_from(KnowledgeDocument)
            .where(KnowledgeDocument.source_id == source.id)
        )
        chunk_count = await db.execute(
            text("SELECT COUNT(*) FROM knowledge_chunks kc JOIN knowledge_documents kd ON kd.id = kc.document_id WHERE kd.source_id = :sid"),
            {"sid": str(source.id)},
        )
        source.doc_count = doc_count.scalar() or 0
        source.chunk_count = chunk_count.scalar() or 0
        source.sync_status = "completed"
        source.last_synced_at = datetime.now(timezone.utc)
        source.sync_error = "; ".join(stats["errors"]) if stats["errors"] else None
        await db.commit()

        logger.info(
            "Sync completed for source %s: fetched=%d new=%d updated=%d unchanged=%d chunks=%d errors=%d",
            source.name, stats["docs_fetched"], stats["docs_new"], stats["docs_updated"],
            stats["docs_unchanged"], stats["chunks_created"], len(stats["errors"]),
        )

    except Exception as e:
        logger.error("Sync failed for source %s: %s", source_id, e)
        source.sync_status = "failed"
        source.sync_error = str(e)[:2000]
        await db.commit()
        stats["errors"].append(str(e))

    return {"status": source.sync_status, **stats}


async def sync_all_due_sources(db: AsyncSession) -> List[dict]:
    """Sync all active sources whose sync interval has elapsed. Called by the scheduler."""
    if not await is_rag_enabled(db):
        return []

    result = await db.execute(
        select(KnowledgeSource).where(
            KnowledgeSource.is_active == True,  # noqa: E712
            KnowledgeSource.sync_status != "running",
        )
    )
    sources = result.scalars().all()
    results = []

    now = datetime.now(timezone.utc)
    for source in sources:
        if source.last_synced_at:
            hours_since = (now - source.last_synced_at).total_seconds() / 3600
            if hours_since < source.sync_interval_hours:
                continue

        logger.info("Scheduled sync starting for source: %s", source.name)
        sync_result = await sync_source(str(source.id), db)
        results.append({"source": source.name, **sync_result})

    return results
