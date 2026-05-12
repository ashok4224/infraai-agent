"""Pydantic schemas for Identity Provider management."""
from pydantic import BaseModel
from typing import Optional
from uuid import UUID
from datetime import datetime


class IdentityProviderCreate(BaseModel):
    name: str
    protocol: str  # oidc | saml
    is_active: bool = True
    is_default: bool = False
    # OIDC
    oidc_issuer_url: Optional[str] = None
    oidc_client_id: Optional[str] = None
    oidc_client_secret: Optional[str] = None
    oidc_scopes: Optional[str] = "openid profile email"
    oidc_redirect_uri: Optional[str] = None
    # SAML
    saml_entity_id: Optional[str] = None
    saml_idp_metadata_url: Optional[str] = None
    saml_idp_metadata_xml: Optional[str] = None
    saml_acs_url: Optional[str] = None
    saml_slo_url: Optional[str] = None
    saml_certificate: Optional[str] = None
    # Provisioning
    auto_provision: bool = True
    default_role: str = "viewer"
    group_role_mapping: Optional[dict] = None
    scim_token: Optional[str] = None


class IdentityProviderUpdate(BaseModel):
    name: Optional[str] = None
    protocol: Optional[str] = None
    is_active: Optional[bool] = None
    is_default: Optional[bool] = None
    oidc_issuer_url: Optional[str] = None
    oidc_client_id: Optional[str] = None
    oidc_client_secret: Optional[str] = None
    oidc_scopes: Optional[str] = None
    oidc_redirect_uri: Optional[str] = None
    saml_entity_id: Optional[str] = None
    saml_idp_metadata_url: Optional[str] = None
    saml_idp_metadata_xml: Optional[str] = None
    saml_acs_url: Optional[str] = None
    saml_slo_url: Optional[str] = None
    saml_certificate: Optional[str] = None
    auto_provision: Optional[bool] = None
    default_role: Optional[str] = None
    group_role_mapping: Optional[dict] = None
    scim_token: Optional[str] = None


class IdentityProviderResponse(BaseModel):
    id: UUID
    name: str
    protocol: str
    is_active: bool
    is_default: bool
    oidc_issuer_url: Optional[str] = None
    oidc_client_id: Optional[str] = None
    oidc_scopes: Optional[str] = None
    oidc_redirect_uri: Optional[str] = None
    saml_entity_id: Optional[str] = None
    saml_idp_metadata_url: Optional[str] = None
    saml_acs_url: Optional[str] = None
    saml_slo_url: Optional[str] = None
    auto_provision: bool
    default_role: str
    group_role_mapping: Optional[dict] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SSOProviderPublic(BaseModel):
    """Public-facing IDP info shown on the login page (no secrets)."""
    id: UUID
    name: str
    protocol: str
    is_default: bool

    model_config = {"from_attributes": True}


class SSOLoginURLResponse(BaseModel):
    redirect_url: str


class SSOCallbackRequest(BaseModel):
    code: Optional[str] = None
    state: Optional[str] = None
    # SAML uses form-post, handled separately
