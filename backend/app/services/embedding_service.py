"""Multi-provider embedding service for RAG vectorization."""
import logging
from typing import List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.ai_config import AIProviderConfig
from app.services.rag_utils import get_rag_settings

logger = logging.getLogger(__name__)

# Batch limits per provider
_OPENAI_BATCH_SIZE = 100


async def _get_embedding_client(db: AsyncSession) -> tuple:
    """Resolve an active AI provider that supports embeddings.

    Prefers OpenAI / Azure OpenAI / Azure Foundry.  Falls back to any
    active provider only when none of those are configured.
    """
    _EMBEDDING_PROVIDERS = ("openai", "azure_openai", "azure_foundry")
    # Try embedding-capable providers first
    result = await db.execute(
        select(AIProviderConfig).where(
            AIProviderConfig.is_active == True,  # noqa: E712
            AIProviderConfig.provider.in_(_EMBEDDING_PROVIDERS),
        ).order_by(AIProviderConfig.is_default.desc())
    )
    config = result.scalars().first()
    if config:
        return config

    # Fallback: any active provider (will likely fail for Anthropic/Google
    # but keeps existing behaviour and surfaces a clear error)
    result = await db.execute(
        select(AIProviderConfig).where(
            AIProviderConfig.is_active == True  # noqa: E712
        ).order_by(AIProviderConfig.is_default.desc())
    )
    config = result.scalars().first()
    if not config:
        raise RuntimeError("No active AI provider configured for embeddings")
    return config


async def embed_text(text: str, db: AsyncSession) -> List[float]:
    """Generate embedding vector for a single text string."""
    results = await embed_batch([text], db)
    return results[0]


async def embed_batch(texts: List[str], db: AsyncSession) -> List[List[float]]:
    """Generate embedding vectors for a batch of texts. Returns list of float vectors."""
    if not texts:
        return []

    config = await _get_embedding_client(db)
    rag_settings = await get_rag_settings(db)
    model = rag_settings.get("rag_embedding_model", "text-embedding-3-small")

    provider = config.provider.lower()
    all_embeddings: List[List[float]] = []

    if provider in ("openai", "azure_openai"):
        import openai

        client_kwargs = {}
        if provider == "azure_openai":
            client_kwargs["api_key"] = config.api_key
            client_kwargs["base_url"] = config.base_url
            client = openai.AzureOpenAI(**client_kwargs)
        else:
            client_kwargs["api_key"] = config.api_key
            if config.base_url:
                client_kwargs["base_url"] = config.base_url
            client = openai.OpenAI(**client_kwargs)

        # Process in batches
        for i in range(0, len(texts), _OPENAI_BATCH_SIZE):
            batch = texts[i : i + _OPENAI_BATCH_SIZE]
            response = client.embeddings.create(input=batch, model=model)
            batch_embeddings = [item.embedding for item in response.data]
            all_embeddings.extend(batch_embeddings)

    elif provider == "azure_foundry":
        # Use Azure AI Foundry endpoint for embeddings
        import openai
        from azure.identity import ClientSecretCredential
        from app.config import settings as app_settings

        credential = ClientSecretCredential(
            tenant_id=app_settings.AZURE_TENANT_ID,
            client_id=app_settings.AZURE_CLIENT_ID,
            client_secret=app_settings.AZURE_CLIENT_SECRET,
        )
        token = credential.get_token("https://cognitiveservices.azure.com/.default")

        client = openai.AzureOpenAI(
            api_key=token.token,
            azure_endpoint=app_settings.AZURE_AI_FOUNDRY_ENDPOINT,
            api_version="2024-06-01",
        )
        for i in range(0, len(texts), _OPENAI_BATCH_SIZE):
            batch = texts[i : i + _OPENAI_BATCH_SIZE]
            response = client.embeddings.create(input=batch, model=model)
            batch_embeddings = [item.embedding for item in response.data]
            all_embeddings.extend(batch_embeddings)

    else:
        raise RuntimeError(f"Embedding not supported for provider '{provider}'. Use OpenAI, Azure OpenAI, or Azure Foundry.")

    logger.info("Generated %d embeddings using %s/%s", len(all_embeddings), provider, model)
    return all_embeddings
