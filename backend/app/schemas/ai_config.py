from pydantic import BaseModel
from typing import Optional
from uuid import UUID
from datetime import datetime


class AIProviderConfigCreate(BaseModel):
    model_config = {"protected_namespaces": ()}

    provider: str
    display_name: str
    api_key: Optional[str] = None
    model_name: str
    base_url: Optional[str] = None
    is_active: bool = False
    is_default: bool = False
    max_tokens: int = 4096
    temperature: float = 0.2
    extra_params: dict = {}


class AIProviderConfigUpdate(BaseModel):
    model_config = {"protected_namespaces": ()}

    display_name: Optional[str] = None
    api_key: Optional[str] = None
    model_name: Optional[str] = None
    base_url: Optional[str] = None
    is_active: Optional[bool] = None
    is_default: Optional[bool] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    extra_params: Optional[dict] = None


class AIProviderConfigResponse(BaseModel):
    model_config = {"protected_namespaces": (), "from_attributes": True}

    id: UUID
    provider: str
    display_name: str
    model_name: str
    base_url: Optional[str]
    is_active: bool
    is_default: bool
    max_tokens: int
    temperature: float
    extra_params: dict
    has_api_key: bool = False
    created_at: datetime
    updated_at: datetime
