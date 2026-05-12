"""PII / sensitive-data redaction before sending alert context to AI models.

Strips or masks personally identifiable information, credentials, and other
sensitive tokens from alert text so that data-breach risk is minimised when
the prompt leaves the organisational boundary.

Usage:
    from app.services.pii_redactor import redact_text, redact_dict
    clean_prompt = redact_text(raw_prompt)
    clean_labels = redact_dict(raw_labels)
"""
import re
from typing import Any

# ── Pattern catalogue ────────────────────────────────────────────────────

_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Email addresses
    (re.compile(r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b'), '[REDACTED_EMAIL]'),
    # IP addresses (IPv4)
    (re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'), '[REDACTED_IP]'),
    # Credit card numbers (13-19 digits, optionally spaced/dashed)
    (re.compile(r'\b(?:\d[ \-]?){13,19}\b'), '[REDACTED_CC]'),
    # SSN (US)
    (re.compile(r'\b\d{3}-\d{2}-\d{4}\b'), '[REDACTED_SSN]'),
    # Phone numbers (various formats)
    (re.compile(r'\b(?:\+?1[\- ]?)?\(?\d{3}\)?[\- ]?\d{3}[\- ]?\d{4}\b'), '[REDACTED_PHONE]'),
    # AWS access key
    (re.compile(r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b'), '[REDACTED_AWS_KEY]'),
    # Generic API key / token patterns (hex/base64 ≥ 20 chars after key= or token= or secret=)
    (re.compile(r'(?i)(?:api[_-]?key|token|secret|password|passwd|pwd|authorization)\s*[:=]\s*["\']?([A-Za-z0-9/+=_\-.]{20,})["\']?'), '[REDACTED_SECRET]'),
    # Bearer tokens
    (re.compile(r'(?i)Bearer\s+[A-Za-z0-9\-._~+/]+=*'), 'Bearer [REDACTED_TOKEN]'),
    # Connection strings with embedded passwords
    (re.compile(r'(?i)(?:password|pwd)\s*=\s*[^\s;,&"\']+'), 'password=[REDACTED]'),
    # Private keys
    (re.compile(r'-----BEGIN\s[\w\s]+PRIVATE\sKEY-----[\s\S]*?-----END\s[\w\s]+PRIVATE\sKEY-----'), '[REDACTED_PRIVATE_KEY]'),
    # Hostnames with internal domain patterns (customize per org)
    # By default we do NOT redact hostnames — they're needed for diagnosis.
    # Uncomment if your org requires it:
    # (re.compile(r'\b[a-z0-9\-]+\.internal\.[a-z]+\b', re.IGNORECASE), '[REDACTED_HOSTNAME]'),
]

# Labels/annotation keys whose values should always be fully masked
_SENSITIVE_KEYS = frozenset({
    'password', 'passwd', 'pwd', 'secret', 'api_key', 'apikey',
    'token', 'access_token', 'refresh_token', 'authorization',
    'private_key', 'ssh_password', 'ssh_private_key', 'sudo_password',
    'credit_card', 'ssn', 'social_security',
})


def redact_text(text: str) -> str:
    """Apply all PII patterns to a plain-text string."""
    if not text:
        return text
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact_dict(data: dict[str, Any], depth: int = 0) -> dict[str, Any]:
    """Recursively redact values in a dict.

    - Keys matching _SENSITIVE_KEYS are fully masked.
    - String values are run through ``redact_text``.
    - Nested dicts/lists are recursed up to 6 levels deep.
    """
    if depth > 6:
        return data
    cleaned: dict[str, Any] = {}
    for key, value in data.items():
        if key.lower() in _SENSITIVE_KEYS:
            cleaned[key] = '[REDACTED]'
        elif isinstance(value, str):
            cleaned[key] = redact_text(value)
        elif isinstance(value, dict):
            cleaned[key] = redact_dict(value, depth + 1)
        elif isinstance(value, list):
            cleaned[key] = [
                redact_dict(item, depth + 1) if isinstance(item, dict)
                else redact_text(item) if isinstance(item, str)
                else item
                for item in value
            ]
        else:
            cleaned[key] = value
    return cleaned
