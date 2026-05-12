"""SSO authentication router — OIDC and SAML login/callback endpoints."""
import logging
import secrets
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.idp import IdentityProvider
from app.schemas.idp import SSOProviderPublic, SSOLoginURLResponse
from app.schemas.user import Token
from app.auth.jwt_handler import create_access_token, get_or_create_sso_user

logger = logging.getLogger(__name__)
router = APIRouter()

# In-memory store for OIDC state/nonce pairs (short-lived)
# In production, use Redis or encrypted cookies.
_pending_flows: dict[str, dict] = {}

# Short-lived one-time exchange codes for SAML callback (avoids JWT in URL)
# code → {"token": jwt_string, "expires": datetime}
_exchange_codes: dict[str, dict] = {}


@router.get("/providers", response_model=list[SSOProviderPublic])
async def list_sso_providers(db: AsyncSession = Depends(get_db)):
    """Public endpoint — returns active IDPs for the login page."""
    result = await db.execute(
        select(IdentityProvider)
        .where(IdentityProvider.is_active == True)
        .order_by(IdentityProvider.is_default.desc(), IdentityProvider.name)
    )
    return result.scalars().all()


@router.get("/auth-config")
async def get_auth_config(db: AsyncSession = Depends(get_db)):
    """Public endpoint — returns auth configuration for the login page."""
    from app.models.app_settings import AppSetting

    result = await db.execute(
        select(AppSetting).where(AppSetting.key == "auth_local_enabled")
    )
    setting = result.scalar_one_or_none()
    local_enabled = True
    if setting:
        local_enabled = setting.value.lower() in ("true", "1", "yes")

    providers_result = await db.execute(
        select(IdentityProvider)
        .where(IdentityProvider.is_active == True)
        .order_by(IdentityProvider.is_default.desc(), IdentityProvider.name)
    )
    providers = [
        SSOProviderPublic.model_validate(p) for p in providers_result.scalars().all()
    ]

    return {
        "local_auth_enabled": local_enabled,
        "sso_providers": providers,
    }


# ── OIDC Flow ────────────────────────────────────────────────────────────────

@router.get("/{idp_id}/login")
async def sso_login(idp_id: UUID, db: AsyncSession = Depends(get_db)):
    """Initiate SSO login — redirects the browser to the IDP."""
    result = await db.execute(
        select(IdentityProvider).where(IdentityProvider.id == idp_id)
    )
    idp = result.scalar_one_or_none()
    if not idp or not idp.is_active:
        raise HTTPException(status_code=404, detail="Identity provider not found or inactive")

    if idp.protocol == "oidc":
        from app.services.oidc_service import get_authorization_url, generate_state_and_nonce

        state, nonce = generate_state_and_nonce()
        _pending_flows[state] = {"idp_id": str(idp_id), "nonce": nonce}
        redirect_url = await get_authorization_url(idp, state, nonce)
        return SSOLoginURLResponse(redirect_url=redirect_url)

    elif idp.protocol == "saml":
        from app.services.saml_service import get_saml_login_url, generate_saml_state

        relay_state = generate_saml_state()
        _pending_flows[relay_state] = {"idp_id": str(idp_id)}
        redirect_url = get_saml_login_url(idp, relay_state)
        return SSOLoginURLResponse(redirect_url=redirect_url)

    raise HTTPException(status_code=400, detail=f"Unsupported protocol: {idp.protocol}")


@router.post("/{idp_id}/callback/oidc", response_model=Token)
async def oidc_callback(
    idp_id: UUID,
    code: str,
    state: str,
    db: AsyncSession = Depends(get_db),
):
    """OIDC authorization code callback — exchanges code for tokens and provisions user."""
    # Validate state
    flow = _pending_flows.pop(state, None)
    if not flow or flow.get("idp_id") != str(idp_id):
        raise HTTPException(status_code=400, detail="Invalid or expired SSO state")

    nonce = flow.get("nonce")

    result = await db.execute(
        select(IdentityProvider).where(IdentityProvider.id == idp_id)
    )
    idp = result.scalar_one_or_none()
    if not idp or not idp.is_active:
        raise HTTPException(status_code=404, detail="Identity provider not found")

    from app.services.oidc_service import (
        exchange_code_for_tokens,
        validate_id_token,
        get_userinfo,
        extract_user_info,
    )

    # Exchange code
    tokens = await exchange_code_for_tokens(idp, code)

    # Validate ID token
    id_token = tokens.get("id_token")
    if not id_token:
        raise HTTPException(status_code=400, detail="No id_token received from IDP")

    claims = await validate_id_token(idp, id_token, nonce=nonce)

    # Optional: get userinfo for extra attributes
    access_token = tokens.get("access_token")
    userinfo = {}
    if access_token:
        userinfo = await get_userinfo(idp, access_token)

    # Extract normalized user info
    info = extract_user_info(claims, userinfo)

    if not info.get("email"):
        raise HTTPException(status_code=400, detail="IDP did not provide an email address")

    # JIT provision / update
    user = await get_or_create_sso_user(
        db=db,
        email=info["email"],
        full_name=info["name"],
        idp_id=idp_id,
        subject_id=info["sub"],
        groups=info.get("groups", []),
        idp=idp,
        auth_source="oidc",
    )

    await db.commit()

    # Issue InfraAI JWT
    token = create_access_token(
        data={"sub": str(user.id), "role": user.role, "email": user.email}
    )
    return Token(access_token=token)


@router.post("/{idp_id}/callback/saml", response_model=Token)
async def saml_callback(
    idp_id: UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """SAML Assertion Consumer Service (ACS) — processes SAML Response POST."""
    form_data = await request.form()
    saml_response = form_data.get("SAMLResponse")
    relay_state = form_data.get("RelayState", "")

    if not saml_response:
        raise HTTPException(status_code=400, detail="Missing SAMLResponse")

    # Validate relay state if present
    if relay_state:
        flow = _pending_flows.pop(relay_state, None)
        if not flow or flow.get("idp_id") != str(idp_id):
            raise HTTPException(status_code=400, detail="Invalid or expired SAML relay state")

    result = await db.execute(
        select(IdentityProvider).where(IdentityProvider.id == idp_id)
    )
    idp = result.scalar_one_or_none()
    if not idp or not idp.is_active:
        raise HTTPException(status_code=404, detail="Identity provider not found")

    from app.services.saml_service import process_saml_response

    info = process_saml_response(idp, saml_response)

    if not info.get("email"):
        raise HTTPException(status_code=400, detail="SAML assertion did not contain an email address")

    # JIT provision / update
    user = await get_or_create_sso_user(
        db=db,
        email=info["email"],
        full_name=info["name"],
        idp_id=idp_id,
        subject_id=info["sub"],
        groups=info.get("groups", []),
        idp=idp,
        auth_source="saml",
    )

    await db.commit()

    # Issue InfraAI JWT
    token = create_access_token(
        data={"sub": str(user.id), "role": user.role, "email": user.email}
    )

    # SAML ACS is a form POST from the IDP — redirect back to frontend with a
    # short-lived one-time exchange code (NOT the raw JWT, which would leak in
    # browser history and Referer headers).
    from datetime import datetime, timedelta, timezone

    code = secrets.token_urlsafe(48)
    _exchange_codes[code] = {
        "token": token,
        "expires": datetime.now(timezone.utc) + timedelta(seconds=60),
    }
    frontend_url = f"/sso/callback?code={code}"
    return RedirectResponse(url=frontend_url, status_code=303)


# ── Exchange a one-time code for a JWT (used by SAML callback) ───────────────

@router.post("/exchange", response_model=Token)
async def exchange_code(code: str):
    """Exchange a short-lived one-time code for a JWT access token.

    Used by the frontend SSOCallbackPage after SAML redirects to
    ``/sso/callback?code=...`` instead of exposing the JWT in the URL.
    """
    from datetime import datetime, timezone

    # Purge expired codes
    now = datetime.now(timezone.utc)
    expired = [k for k, v in _exchange_codes.items() if v["expires"] <= now]
    for k in expired:
        del _exchange_codes[k]

    entry = _exchange_codes.pop(code, None)
    if not entry:
        raise HTTPException(status_code=400, detail="Invalid or expired exchange code")

    return Token(access_token=entry["token"])


# ── SAML SP Metadata ─────────────────────────────────────────────────────────

@router.get("/{idp_id}/metadata")
async def saml_sp_metadata(idp_id: UUID, db: AsyncSession = Depends(get_db)):
    """Return SAML SP metadata XML for configuring the IDP."""
    result = await db.execute(
        select(IdentityProvider).where(IdentityProvider.id == idp_id)
    )
    idp = result.scalar_one_or_none()
    if not idp:
        raise HTTPException(status_code=404, detail="Identity provider not found")
    if idp.protocol != "saml":
        raise HTTPException(status_code=400, detail="This endpoint is only for SAML providers")

    from app.services.saml_service import get_sp_metadata
    from fastapi.responses import Response

    metadata_xml = get_sp_metadata(idp)
    return Response(content=metadata_xml, media_type="application/xml")
