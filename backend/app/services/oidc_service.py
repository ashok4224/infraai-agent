"""OIDC (OpenID Connect) service — handles discovery, auth URL, token exchange, and validation."""
import hashlib
import logging
import secrets
from urllib.parse import urlencode

import httpx
from jose import jwt as jose_jwt, JWTError

from app.models.idp import IdentityProvider

logger = logging.getLogger(__name__)

# In-memory cache for OIDC discovery documents (keyed by issuer URL)
_discovery_cache: dict[str, dict] = {}


async def _get_discovery(issuer_url: str) -> dict:
    """Fetch and cache the OIDC .well-known/openid-configuration document."""
    if issuer_url in _discovery_cache:
        return _discovery_cache[issuer_url]

    well_known = issuer_url.rstrip("/") + "/.well-known/openid-configuration"
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(well_known)
        resp.raise_for_status()
        doc = resp.json()

    _discovery_cache[issuer_url] = doc
    return doc


async def _get_jwks(jwks_uri: str) -> dict:
    """Fetch the JSON Web Key Set from the IDP."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(jwks_uri)
        resp.raise_for_status()
        return resp.json()


def generate_state_and_nonce() -> tuple[str, str]:
    """Generate cryptographic random state and nonce for OIDC flow."""
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    return state, nonce


async def get_authorization_url(idp: IdentityProvider, state: str, nonce: str) -> str:
    """Build the OIDC authorization URL to redirect the user to."""
    if not idp.oidc_issuer_url or not idp.oidc_client_id:
        raise ValueError("OIDC issuer URL and client ID are required")

    discovery = await _get_discovery(idp.oidc_issuer_url)
    auth_endpoint = discovery["authorization_endpoint"]

    params = {
        "client_id": idp.oidc_client_id,
        "response_type": "code",
        "scope": idp.oidc_scopes or "openid profile email",
        "redirect_uri": idp.oidc_redirect_uri,
        "state": state,
        "nonce": nonce,
        "response_mode": "query",
    }
    return f"{auth_endpoint}?{urlencode(params)}"


async def exchange_code_for_tokens(idp: IdentityProvider, code: str) -> dict:
    """Exchange the authorization code for ID token, access token, etc."""
    discovery = await _get_discovery(idp.oidc_issuer_url)
    token_endpoint = discovery["token_endpoint"]

    payload = {
        "grant_type": "authorization_code",
        "client_id": idp.oidc_client_id,
        "client_secret": idp.oidc_client_secret,
        "code": code,
        "redirect_uri": idp.oidc_redirect_uri,
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(token_endpoint, data=payload)
        if resp.status_code != 200:
            logger.error("OIDC token exchange failed: %s %s", resp.status_code, resp.text)
            raise ValueError(f"Token exchange failed: {resp.status_code}")
        return resp.json()


async def validate_id_token(idp: IdentityProvider, id_token: str, nonce: str | None = None) -> dict:
    """Validate and decode the OIDC ID token.

    Returns the claims dict (sub, email, name, groups, etc.).
    """
    discovery = await _get_discovery(idp.oidc_issuer_url)
    jwks_uri = discovery["jwks_uri"]
    jwks = await _get_jwks(jwks_uri)

    # Decode without verification first to get the key ID
    unverified = jose_jwt.get_unverified_header(id_token)
    kid = unverified.get("kid")

    # Find matching key
    rsa_key = {}
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            rsa_key = key
            break

    if not rsa_key:
        raise ValueError("Unable to find matching JWK for token verification")

    try:
        claims = jose_jwt.decode(
            id_token,
            rsa_key,
            algorithms=["RS256", "RS384", "RS512"],
            audience=idp.oidc_client_id,
            issuer=idp.oidc_issuer_url.rstrip("/") + "/",
            options={"verify_at_hash": False},
        )
    except JWTError:
        # Some IDPs don't have trailing slash — try without
        claims = jose_jwt.decode(
            id_token,
            rsa_key,
            algorithms=["RS256", "RS384", "RS512"],
            audience=idp.oidc_client_id,
            issuer=idp.oidc_issuer_url.rstrip("/"),
            options={"verify_at_hash": False},
        )

    # Validate nonce
    if nonce and claims.get("nonce") != nonce:
        raise ValueError("Nonce mismatch — potential replay attack")

    return claims


async def get_userinfo(idp: IdentityProvider, access_token: str) -> dict:
    """Call the OIDC userinfo endpoint to get user attributes."""
    discovery = await _get_discovery(idp.oidc_issuer_url)
    userinfo_endpoint = discovery.get("userinfo_endpoint")
    if not userinfo_endpoint:
        return {}

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            userinfo_endpoint,
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if resp.status_code != 200:
            logger.warning("Userinfo failed: %s", resp.status_code)
            return {}
        return resp.json()


def extract_user_info(id_claims: dict, userinfo: dict | None = None) -> dict:
    """Extract normalized user info from OIDC claims + optional userinfo response.

    Returns: {"sub": ..., "email": ..., "name": ..., "groups": [...]}
    """
    merged = {**id_claims}
    if userinfo:
        merged.update(userinfo)

    email = merged.get("email") or merged.get("preferred_username") or merged.get("upn", "")
    name = merged.get("name") or merged.get("given_name", "")
    if not name and merged.get("given_name"):
        name = f"{merged.get('given_name', '')} {merged.get('family_name', '')}".strip()

    # Groups come in various claims depending on the IDP
    groups = merged.get("groups", [])
    if not groups:
        groups = merged.get("roles", [])

    return {
        "sub": merged.get("sub", ""),
        "email": email,
        "name": name or email.split("@")[0],
        "groups": groups if isinstance(groups, list) else [],
    }


async def test_oidc_connection(idp: IdentityProvider) -> dict:
    """Test OIDC IDP connectivity by fetching discovery document."""
    try:
        discovery = await _get_discovery(idp.oidc_issuer_url)
        # Invalidate cache so next real auth uses fresh data
        _discovery_cache.pop(idp.oidc_issuer_url, None)
        return {
            "success": True,
            "issuer": discovery.get("issuer"),
            "authorization_endpoint": discovery.get("authorization_endpoint"),
            "token_endpoint": discovery.get("token_endpoint"),
        }
    except Exception as e:
        return {"success": False, "error": str(e)}
