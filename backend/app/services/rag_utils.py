"""RAG feature toggle guard — checks if RAG is enabled before performing KB operations."""
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.app_settings import AppSetting
from app.config import settings

logger = logging.getLogger(__name__)


async def is_rag_enabled(db: AsyncSession) -> bool:
    """Check whether RAG is enabled (DB setting overrides env default)."""
    try:
        result = await db.execute(
            select(AppSetting.value).where(AppSetting.key == "rag_enabled")
        )
        db_val = result.scalar_one_or_none()
        if db_val is not None:
            return db_val.lower() in ("true", "1", "yes")
    except Exception:
        pass
    return settings.RAG_ENABLED


async def get_rag_settings(db: AsyncSession) -> dict:
    """Return all rag_* settings as a typed dict."""
    defaults = {
        "rag_enabled": False,
        "rag_embedding_model": "text-embedding-3-small",
        "rag_chunk_size": 500,
        "rag_chunk_overlap": 50,
        "rag_top_k": 5,
        "rag_score_threshold": 0.7,
    }
    try:
        result = await db.execute(
            select(AppSetting).where(AppSetting.key.like("rag_%"))
        )
        for row in result.scalars().all():
            if row.key in defaults:
                val = row.value
                if isinstance(defaults[row.key], bool):
                    defaults[row.key] = val.lower() in ("true", "1", "yes")
                elif isinstance(defaults[row.key], int):
                    defaults[row.key] = int(val)
                elif isinstance(defaults[row.key], float):
                    defaults[row.key] = float(val)
                else:
                    defaults[row.key] = val
    except Exception as e:
        logger.warning("Failed to load RAG settings from DB, using defaults: %s", e)
    return defaults
