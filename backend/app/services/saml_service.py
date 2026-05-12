"""SAML 2.0 service — AuthnRequest generation, Response validation, attribute extraction.

Uses pysaml2 for spec-compliant SAML handling:  signature verification,
audience restriction, time bounds, and replay prevention.
"""
import logging
import secrets
import tempfile
import os
from base64 import b64decode, b64encode
from urllib.parse import urlencode
from xml.etree import ElementTree

import httpx

from app.models.idp import IdentityProvider

logger = logging.getLogger(__name__)

# Track consumed assertion IDs to prevent replay
_consumed_assertions: set[str] = set()


def _get_saml_client(idp: IdentityProvider):
    """Build a pysaml2 Saml2Client for the given IDP config."""
    from saml2 import BINDING_HTTP_POST, BINDING_HTTP_REDIRECT
    from saml2.client import Saml2Client
    from saml2.config import Config as Saml2Config

    config = {
        "entityid": idp.saml_entity_id or idp.saml_acs_url,
        "service": {
            "sp": {
                "endpoints": {
                    "assertion_consumer_service": [
                        (idp.saml_acs_url, BINDING_HTTP_POST),
                    ],
                },
                "allow_unsolicited": True,
                "authn_requests_signed": False,
                "want_assertions_signed": True,
            },
        },
    }

    # Load IDP metadata
    if idp.saml_idp_metadata_xml:
        # Write to temp file for pysaml2
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xml", mode="w", encoding="utf-8")
        tmp.write(idp.saml_idp_metadata_xml)
        tmp.close()
        config["metadata"] = {"local": [tmp.name]}
    elif idp.saml_idp_metadata_url:
        config["metadata"] = {"remote": [{"url": idp.saml_idp_metadata_url}]}

    # IDP certificate for signature verification
    if idp.saml_certificate:
        cert_tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pem", mode="w", encoding="utf-8")
        cert_content = idp.saml_certificate
        if not cert_content.startswith("-----BEGIN"):
            cert_content = f"-----BEGIN CERTIFICATE-----\n{cert_content}\n-----END CERTIFICATE-----"
        cert_tmp.write(cert_content)
        cert_tmp.close()
        config["cert_file"] = cert_tmp.name

    saml_config = Saml2Config()
    saml_config.load(config)
    return Saml2Client(config=saml_config)


def generate_saml_state() -> str:
    """Generate a relay state token for SAML flow."""
    return secrets.token_urlsafe(32)


def get_saml_login_url(idp: IdentityProvider, relay_state: str) -> str:
    """Build the SAML AuthnRequest redirect URL.

    Returns the full URL to redirect the user's browser to the IDP.
    """
    from saml2 import BINDING_HTTP_REDIRECT

    client = _get_saml_client(idp)
    reqid, info = client.prepare_for_authenticate(
        relay_state=relay_state,
        binding=BINDING_HTTP_REDIRECT,
    )
    # info is a dict with headers; the Location header has the redirect URL
    for key, value in info["headers"]:
        if key == "Location":
            return value

    raise ValueError("Could not generate SAML AuthnRequest redirect URL")


def process_saml_response(idp: IdentityProvider, saml_response: str) -> dict:
    """Validate a SAML Response and extract user attributes.

    Args:
        idp: The identity provider configuration.
        saml_response: Base64-encoded SAMLResponse from the IDP POST.

    Returns:
        {"sub": ..., "email": ..., "name": ..., "groups": [...]}

    Raises:
        ValueError: If the response is invalid, expired, or replayed.
    """
    from saml2 import BINDING_HTTP_POST

    client = _get_saml_client(idp)

    try:
        authn_response = client.parse_authn_request_response(
            saml_response,
            BINDING_HTTP_POST,
        )
    except Exception as e:
        logger.error("SAML response validation failed: %s", e)
        raise ValueError(f"Invalid SAML response: {e}") from e

    if authn_response is None:
        raise ValueError("SAML response could not be parsed")

    # Replay prevention
    assertion_id = authn_response.assertion.id if hasattr(authn_response, "assertion") else None
    if assertion_id:
        if assertion_id in _consumed_assertions:
            raise ValueError("SAML assertion replay detected")
        _consumed_assertions.add(assertion_id)
        # Limit memory — keep only recent 10000
        if len(_consumed_assertions) > 10000:
            _consumed_assertions.clear()

    # Extract identity info
    identity = authn_response.get_identity()
    name_id = authn_response.get_subject()
    session_info = authn_response.session_info()

    email = ""
    name = ""
    groups = []

    # Try common SAML attribute names
    email_attrs = [
        "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
        "email",
        "Email",
        "mail",
        "http://schemas.xmlsoap.org/claims/EmailAddress",
    ]
    for attr in email_attrs:
        vals = identity.get(attr, [])
        if vals:
            email = vals[0]
            break

    name_attrs = [
        "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/name",
        "displayName",
        "name",
        "http://schemas.microsoft.com/identity/claims/displayname",
    ]
    for attr in name_attrs:
        vals = identity.get(attr, [])
        if vals:
            name = vals[0]
            break

    if not name:
        first = identity.get("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/givenname", [""])[0]
        last = identity.get("http://schemas.xmlsoap.org/ws/2005/05/identity/claims/surname", [""])[0]
        name = f"{first} {last}".strip()

    group_attrs = [
        "http://schemas.microsoft.com/ws/2008/06/identity/claims/groups",
        "http://schemas.xmlsoap.org/claims/Group",
        "memberOf",
        "groups",
    ]
    for attr in group_attrs:
        vals = identity.get(attr, [])
        if vals:
            groups = list(vals)
            break

    sub = str(name_id) if name_id else email

    return {
        "sub": sub,
        "email": email or sub,
        "name": name or email.split("@")[0] if email else sub,
        "groups": groups,
    }


def get_sp_metadata(idp: IdentityProvider) -> str:
    """Generate SAML Service Provider metadata XML for this IDP config.

    This is used to configure the IDP side (upload to Azure AD, Okta, etc.).
    """
    client = _get_saml_client(idp)
    return client.config.create_metadata_string()


async def test_saml_connection(idp: IdentityProvider) -> dict:
    """Test SAML IDP connectivity by fetching/parsing metadata."""
    try:
        if idp.saml_idp_metadata_url:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(idp.saml_idp_metadata_url)
                resp.raise_for_status()
                # Parse XML to confirm valid metadata
                ElementTree.fromstring(resp.text)
                return {
                    "success": True,
                    "metadata_url": idp.saml_idp_metadata_url,
                    "metadata_size": len(resp.text),
                }
        elif idp.saml_idp_metadata_xml:
            ElementTree.fromstring(idp.saml_idp_metadata_xml)
            return {
                "success": True,
                "metadata_source": "inline XML",
                "metadata_size": len(idp.saml_idp_metadata_xml),
            }
        else:
            return {"success": False, "error": "No SAML metadata URL or XML configured"}
    except Exception as e:
        return {"success": False, "error": str(e)}
