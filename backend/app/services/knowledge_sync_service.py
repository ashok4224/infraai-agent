"""Knowledge sync service — orchestrates fetch → chunk → embed → store pipeline."""
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, delete, func

from app.models.knowledge import KnowledgeSource, KnowledgeDocument, KnowledgeChunk
from app.services.knowledge_connectors import get_connector, RawDocument
from app.services.chunker_service import chunk_document
from app.services.embedding_service import embed_batch
from app.services.rag_utils import is_rag_enabled, get_rag_settings
from app.config import settings as app_settings

logger = logging.getLogger(__name__)

# Max chunks per embed_batch call to stay within API limits
_EMBED_BATCH_SIZE = 50


async def _foundry_upload_doc(raw_doc: RawDocument) -> str | None:
    """Upload a document to Foundry Files API + add to knowledge vector store.

    Returns the Foundry file_id, or None on failure.
    Only runs when AZURE_AI_FOUNDRY_ENDPOINT is configured.

    Note: Foundry Files API rejects filenames with '/' (directory separators)
    or leading '.' — we normalize to just the base filename.
    """
    if not app_settings.AZURE_AI_FOUNDRY_ENDPOINT:
        return None
    try:
        from app.services.azure_foundry_service import upload_file_to_foundry, add_file_to_knowledge_store
        # Build a safe filename for Foundry:
        # - Use full path with slashes replaced by underscores (avoids basename collisions)
        # - Strip leading dots
        # - Foundry Files API only accepts specific extensions; replace unsupported ones with .txt
        # - Foundry vector store also rejects certain reserved basenames (e.g. "variables.txt")
        #   so we prefix with "doc_" to ensure uniqueness and avoid reserved names
        _FOUNDRY_SUPPORTED_EXTS = {
            "c", "cpp", "css", "csv", "doc", "docx", "gif", "go", "html", "java",
            "jpeg", "jpg", "js", "json", "md", "pdf", "php", "pkl", "png", "pptx",
            "py", "rb", "tar", "tex", "ts", "txt", "webp", "xlsx", "xml", "zip",
        }
        # Flatten path: replace / with _ and strip leading dots/underscores
        safe_name = raw_doc.title.replace("/", "_").replace("\\", "_").lstrip("._")
        safe_name = safe_name or "unnamed"
        # Replace unsupported extension
        if "." in safe_name:
            base_name, ext = safe_name.rsplit(".", 1)
            ext = ext.lower()
            if ext not in _FOUNDRY_SUPPORTED_EXTS:
                safe_name = base_name + ".txt"
        # Prefix with "doc_" to avoid reserved filenames like "variables.txt"
        safe_name = "doc_" + safe_name
        content_bytes = raw_doc.content.encode("utf-8")
        file_id = await upload_file_to_foundry(safe_name, content_bytes)
        await add_file_to_knowledge_store(file_id)
        return file_id
    except Exception as e:
        logger.warning("Foundry upload failed for '%s': %s", raw_doc.title, e)
        return None


async def _foundry_delete_file(file_id: str) -> None:
    """Delete a file from Foundry Files API (removes it from vector store too)."""
    if not file_id or not app_settings.AZURE_AI_FOUNDRY_ENDPOINT:
        return
    try:
        import httpx
        from app.services.azure_foundry_service import _threads_base, _THREADS_API_VERSION, _threads_headers
        base = _threads_base()
        ver = _THREADS_API_VERSION
        async with httpx.AsyncClient(timeout=15.0) as http:
            await http.delete(f"{base}/files/{file_id}?api-version={ver}", headers=_threads_headers())
        logger.debug("Deleted Foundry file %s", file_id)
    except Exception as e:
        logger.warning("Failed to delete Foundry file %s: %s", file_id, e)


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

        # Get existing document hashes + Foundry file IDs for delta detection
        existing_docs = await db.execute(
            select(KnowledgeDocument.id, KnowledgeDocument.content_hash,
                   KnowledgeDocument.file_path, KnowledgeDocument.doc_metadata)
            .where(KnowledgeDocument.source_id == source.id)
        )
        # existing_map: path → (doc_id, content_hash, foundry_file_id_or_None)
        existing_map = {
            row[2]: (row[0], row[1], (row[3] or {}).get("foundry_file_id"))
            for row in existing_docs.fetchall()
        }
        seen_paths = set()

        for raw_doc in raw_docs:
            path = raw_doc.file_path
            seen_paths.add(path)
            content_hash = raw_doc.content_hash

            if path in existing_map:
                doc_id, old_hash, old_foundry_file_id = existing_map[path]
                if old_hash == content_hash:
                    stats["docs_unchanged"] += 1
                    continue
                # Updated document — delete old chunks and re-index
                await db.execute(
                    delete(KnowledgeChunk).where(KnowledgeChunk.document_id == doc_id)
                )
                # Delete old Foundry file (Foundry will auto-remove from vector store)
                if old_foundry_file_id:
                    await _foundry_delete_file(old_foundry_file_id)
                # Upload updated file to Foundry
                new_foundry_file_id = await _foundry_upload_doc(raw_doc)
                doc_result = await db.execute(
                    select(KnowledgeDocument).where(KnowledgeDocument.id == doc_id)
                )
                doc = doc_result.scalars().first()
                if doc:
                    doc.content_hash = content_hash
                    doc.raw_size_bytes = raw_doc.raw_size_bytes
                    doc.indexed_at = datetime.now(timezone.utc)
                    meta = dict(doc.doc_metadata or {})
                    if new_foundry_file_id:
                        meta["foundry_file_id"] = new_foundry_file_id
                    elif "foundry_file_id" in meta:
                        del meta["foundry_file_id"]
                    doc.doc_metadata = meta
                stats["docs_updated"] += 1
            else:
                # New document — upload to Foundry first
                foundry_file_id = await _foundry_upload_doc(raw_doc)
                merged_meta = {**raw_doc.metadata}
                if foundry_file_id:
                    merged_meta["foundry_file_id"] = foundry_file_id
                doc = KnowledgeDocument(
                    source_id=source.id,
                    title=raw_doc.title,
                    file_path=path,
                    content_hash=content_hash,
                    doc_type=raw_doc.doc_type,
                    raw_size_bytes=raw_doc.raw_size_bytes,
                    doc_metadata=merged_meta,
                )
                db.add(doc)
                await db.flush()
                doc_id = doc.id
                stats["docs_new"] += 1

            # Skip local chunking/embedding when Foundry handles it:
            # Foundry auto-chunks + auto-embeds files in the vector store.
            # We still run local chunk/embed as a fallback when Foundry is NOT configured.
            _foundry_handles_kb = bool(app_settings.AZURE_AI_FOUNDRY_ENDPOINT)

            if _foundry_handles_kb:
                # Foundry auto-chunks & auto-embeds — just record doc exists
                if doc:
                    doc.chunk_count = 0  # managed externally by Foundry
                logger.debug("Skipping local embed for %s (Foundry handles it)", path)
            else:
                # No Foundry — run local chunk → embed → pgvector pipeline
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
                doc_id, _, old_foundry_file_id = existing_map[dpath]
                # Remove from Foundry vector store
                if old_foundry_file_id:
                    await _foundry_delete_file(old_foundry_file_id)
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
