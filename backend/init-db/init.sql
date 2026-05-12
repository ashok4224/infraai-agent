-- This script runs on first PostgreSQL initialization only.
-- It ensures the application database user has proper permissions.
-- If POSTGRES_USER is the app user, this is a no-op safety net.

-- Enable pgvector extension for RAG knowledge base embeddings
CREATE EXTENSION IF NOT EXISTS vector;

-- Grant full privileges on the public schema to the connecting user
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO CURRENT_USER;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO CURRENT_USER;

-- Ensure future tables also get proper permissions
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL PRIVILEGES ON TABLES TO CURRENT_USER;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL PRIVILEGES ON SEQUENCES TO CURRENT_USER;
