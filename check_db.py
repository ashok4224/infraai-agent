import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
import os

async def check():
    url = os.environ['DATABASE_URL']
    engine = create_async_engine(url)
    async with engine.connect() as conn:
        # Check pgvector extension
        r = await conn.execute(text("SELECT extname, extversion FROM pg_extension WHERE extname='vector'"))
        rows = r.fetchall()
        print('pgvector:', rows)
        
        # Check knowledge tables exist
        r2 = await conn.execute(text("SELECT table_name FROM information_schema.tables WHERE table_name IN ('knowledge_sources','knowledge_documents','knowledge_chunks') ORDER BY table_name"))
        print('tables:', r2.fetchall())
        
        # Check if OpenAI embedding provider configured
        r3 = await conn.execute(text("SELECT provider, model_name, is_active, is_default FROM ai_provider_configs WHERE provider IN ('openai','azure_foundry','azure_openai')"))
        print('embedding providers:', r3.fetchall())

asyncio.run(check())
