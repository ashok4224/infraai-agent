from pydantic_settings import BaseSettings
from typing import List
import os


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/infraai"
    SECRET_KEY: str = "dev-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    ADMIN_EMAIL: str = "admin@winfosolutions.com"
    ADMIN_PASSWORD: str = "ChangeMe123!"
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "noreply@winfosolutions.com"
    APP_NAME: str = "InfraAI Agent"
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000"
    # Azure AI Foundry
    AZURE_AI_FOUNDRY_ENDPOINT: str = ""
    AZURE_AI_FOUNDRY_PROJECT: str = ""
    AZURE_AI_FOUNDRY_MODEL_DEPLOYMENT: str = "gpt-4o"
    AZURE_AI_FOUNDRY_KEY: str = ""
    AZURE_TENANT_ID: str = ""
    AZURE_CLIENT_ID: str = ""
    AZURE_CLIENT_SECRET: str = ""
    AZURE_SHAREPOINT_SITE_ID: str = ""
    AZURE_OUTLOOK_SENDER: str = ""
    AZURE_AI_SEARCH_ENDPOINT: str = ""
    AZURE_AI_SEARCH_KEY: str = ""
    AZURE_AI_SEARCH_INDEX: str = ""
    AZURE_KEY_VAULT_URL: str = ""
    # Azure Blob Storage ??? for Knowledge Base file uploads
    # Set AZURE_BLOB_ACCOUNT_URL to enable blob storage (e.g. https://infraaiknowledge.blob.core.windows.net)
    # Uses the same service principal (AZURE_CLIENT_ID/SECRET/TENANT_ID) ??? no extra key needed
    AZURE_BLOB_ACCOUNT_URL: str = ""
    AZURE_BLOB_CONTAINER: str = "knowledge-docs"
    # Authentication
    AUTH_LOCAL_ENABLED: bool = True
    # Encryption key for database secrets (separate from JWT SECRET_KEY)
    # If not set, falls back to SECRET_KEY for backwards compatibility
    ENCRYPTION_KEY: str = ""
    # RAG / Knowledge Base
    RAG_ENABLED: bool = False
    RAG_EMBEDDING_MODEL: str = "text-embedding-3-small"
    RAG_EMBEDDING_DIMENSIONS: int = 1536

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",")]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
