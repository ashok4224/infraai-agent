"""Knowledge Base CRUD + search + sync API — guarded by is_rag_enabled."""
import logging
import os
import uuid
from typing import List, Optional
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete as sa_delete

from app.database import get_db
from app.models.user import User
from app.models.knowledge import KnowledgeSource, KnowledgeDocument, KnowledgeChunk
from app.schemas.knowledge import (
    KnowledgeSourceCreate, KnowledgeSourceUpdate, KnowledgeSourceResponse,
    KnowledgeDocumentResponse,
    KnowledgeSearchRequest, KnowledgeSearchResponse, KnowledgeSearchResult,
    SyncStatusResponse, SyncPreviewResponse,
    RAGSettingsResponse,
)
from app.auth.jwt_handler import get_current_user, require_operator
from app.services.rag_utils import is_rag_enabled, get_rag_settings

logger = logging.getLogger(__name__)
router = APIRouter()

UPLOAD_DIR = os.path.join(os.path.dirname(__file__), "..", "uploads", "knowledge")


async def _require_rag(db: AsyncSession = Depends(get_db)):
    if not await is_rag_enabled(db):
        raise HTTPException(status_code=403, detail="RAG Knowledge Base feature is not enabled")
    return True


# ── RAG settings ────────────────────────────────────────────────────────

@router.get("/settings", response_model=RAGSettingsResponse)
async def get_rag_settings_endpoint(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    settings = await get_rag_settings(db)
    return RAGSettingsResponse(
        rag_enabled=settings.get("rag_enabled", False),
        rag_embedding_model=settings.get("rag_embedding_model", "text-embedding-3-small"),
        rag_chunk_size=int(settings.get("rag_chunk_size", 500)),
        rag_chunk_overlap=int(settings.get("rag_chunk_overlap", 50)),
        rag_top_k=int(settings.get("rag_top_k", 5)),
        rag_score_threshold=float(settings.get("rag_score_threshold", 0.7)),
    )


# ── Sources CRUD ────────────────────────────────────────────────────────

@router.get("/sources", response_model=List[KnowledgeSourceResponse])
async def list_sources(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    _rag=Depends(_require_rag),
):
    result = await db.execute(
        select(KnowledgeSource).order_by(KnowledgeSource.created_at.desc())
    )
    return result.scalars().all()


@router.get("/sources/{source_id}", response_model=KnowledgeSourceResponse)
async def get_source(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    _rag=Depends(_require_rag),
):
    result = await db.execute(
        select(KnowledgeSource).where(KnowledgeSource.id == source_id)
    )
    source = result.scalars().first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


@router.post("/sources", response_model=KnowledgeSourceResponse, status_code=201)
async def create_source(
    payload: KnowledgeSourceCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_operator),
    _rag=Depends(_require_rag),
):
    valid_types = {"github", "sharepoint", "jira", "servicenow", "upload"}
    if payload.source_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"Invalid source_type. Must be one of: {valid_types}")

    source = KnowledgeSource(
        name=payload.name,
        description=payload.description,
        source_type=payload.source_type,
        connection_config=payload.connection_config,
        filter_config=payload.filter_config,
        sync_interval_hours=payload.sync_interval_hours,
        is_active=payload.is_active,
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    return source


@router.put("/sources/{source_id}", response_model=KnowledgeSourceResponse)
async def update_source(
    source_id: uuid.UUID,
    payload: KnowledgeSourceUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_operator),
    _rag=Depends(_require_rag),
):
    result = await db.execute(
        select(KnowledgeSource).where(KnowledgeSource.id == source_id)
    )
    source = result.scalars().first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(source, field, value)

    await db.commit()
    await db.refresh(source)
    return source


@router.delete("/sources/{source_id}", status_code=204)
async def delete_source(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_operator),
    _rag=Depends(_require_rag),
):
    result = await db.execute(
        select(KnowledgeSource).where(KnowledgeSource.id == source_id)
    )
    source = result.scalars().first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    await db.delete(source)
    await db.commit()


# ── Documents ───────────────────────────────────────────────────────────

@router.get("/sources/{source_id}/documents", response_model=List[KnowledgeDocumentResponse])
async def list_documents(
    source_id: uuid.UUID,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    _rag=Depends(_require_rag),
):
    result = await db.execute(
        select(KnowledgeDocument)
        .where(KnowledgeDocument.source_id == source_id)
        .order_by(KnowledgeDocument.indexed_at.desc())
        .offset(skip).limit(limit)
    )
    return result.scalars().all()


# ── Search ──────────────────────────────────────────────────────────────

@router.post("/search", response_model=KnowledgeSearchResponse)
async def search_knowledge(
    payload: KnowledgeSearchRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    _rag=Depends(_require_rag),
):
    from app.services.knowledge_retrieval_service import search_knowledge_base

    source_id_strs = [str(s) for s in payload.source_ids] if payload.source_ids else None
    chunks = await search_knowledge_base(
        payload.query,
        db,
        top_k=payload.top_k,
        score_threshold=payload.score_threshold,
        source_types=payload.source_types,
        source_ids=source_id_strs,
    )
    results = [
        KnowledgeSearchResult(
            chunk_content=c.chunk_content,
            score=c.score,
            document_title=c.document_title,
            source_name=c.source_name,
            source_type=c.source_type,
            file_path=c.file_path,
            doc_metadata=c.metadata,
        )
        for c in chunks
    ]
    return KnowledgeSearchResponse(results=results, query=payload.query, total=len(results))


# ── Sync ────────────────────────────────────────────────────────────────

@router.post("/sources/{source_id}/sync", response_model=SyncStatusResponse)
async def trigger_sync(
    source_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_operator),
    _rag=Depends(_require_rag),
):
    result = await db.execute(
        select(KnowledgeSource).where(KnowledgeSource.id == source_id)
    )
    source = result.scalars().first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    if source.sync_status == "running":
        raise HTTPException(status_code=409, detail="Sync is already running")

    # Run sync in background
    async def _bg_sync():
        from app.database import async_session
        from app.services.knowledge_sync_service import sync_source
        async with async_session() as bg_db:
            await sync_source(str(source_id), bg_db)

    background_tasks.add_task(_bg_sync)

    source.sync_status = "running"
    await db.commit()
    await db.refresh(source)

    return SyncStatusResponse(
        source_id=source.id,
        sync_status=source.sync_status,
        last_synced_at=source.last_synced_at,
        doc_count=source.doc_count,
        chunk_count=source.chunk_count,
        sync_error=source.sync_error,
    )


@router.get("/sources/{source_id}/sync-status", response_model=SyncStatusResponse)
async def get_sync_status(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
    _rag=Depends(_require_rag),
):
    result = await db.execute(
        select(KnowledgeSource).where(KnowledgeSource.id == source_id)
    )
    source = result.scalars().first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    return SyncStatusResponse(
        source_id=source.id,
        sync_status=source.sync_status,
        last_synced_at=source.last_synced_at,
        doc_count=source.doc_count,
        chunk_count=source.chunk_count,
        sync_error=source.sync_error,
    )


@router.post("/sources/{source_id}/test-connection")
async def test_source_connection(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_operator),
    _rag=Depends(_require_rag),
):
    result = await db.execute(
        select(KnowledgeSource).where(KnowledgeSource.id == source_id)
    )
    source = result.scalars().first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    from app.services.knowledge_connectors import get_connector
    connector = get_connector(source.source_type)
    test_result = await connector.test_connection(
        source.connection_config or {},
        source.filter_config or {},
    )
    return test_result


@router.post("/sources/{source_id}/preview", response_model=SyncPreviewResponse)
async def preview_sync(
    source_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_operator),
    _rag=Depends(_require_rag),
):
    result = await db.execute(
        select(KnowledgeSource).where(KnowledgeSource.id == source_id)
    )
    source = result.scalars().first()
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    from app.services.knowledge_connectors import get_connector
    connector = get_connector(source.source_type)
    preview = await connector.preview(
        source.connection_config or {},
        source.filter_config or {},
    )

    est_docs = preview.get("estimated_documents", 0)
    est_chunks = max(1, est_docs * 5)  # rough estimate: 5 chunks per doc
    est_tokens = est_chunks * 500
    # text-embedding-3-small: $0.02 per 1M tokens
    est_cost = (est_tokens / 1_000_000) * 0.02

    return SyncPreviewResponse(
        estimated_documents=est_docs,
        estimated_chunks=est_chunks,
        estimated_tokens=est_tokens,
        estimated_cost_usd=round(est_cost, 4),
        source_type=source.source_type,
        filters_applied=source.filter_config or {},
    )


# ── File upload ─────────────────────────────────────────────────────────

ALLOWED_UPLOAD_EXTENSIONS = {".md", ".txt", ".pdf", ".docx", ".yaml", ".yml", ".json", ".tf", ".hcl"}


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_operator),
    _rag=Depends(_require_rag),
):
    ext = Path(file.filename).suffix.lower() if file.filename else ""
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {ext}")

    upload_dir = Path(UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Sanitize filename
    safe_name = Path(file.filename).name if file.filename else f"{uuid.uuid4()}{ext}"
    dest = upload_dir / safe_name

    content = await file.read()
    if len(content) > 10 * 1024 * 1024:  # 10MB limit
        raise HTTPException(status_code=400, detail="File too large (max 10MB)")

    dest.write_bytes(content)

    return {"filename": safe_name, "size_bytes": len(content), "path": str(dest)}
