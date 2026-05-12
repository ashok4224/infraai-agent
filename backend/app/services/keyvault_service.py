"""Azure Key Vault integration for secure secret storage.

When AZURE_KEY_VAULT_URL is configured, secrets are stored in Azure Key Vault
instead of Fernet-encrypted values in the database. The DB stores only the
Key Vault secret name (prefixed with `kv://`) for reference.

Falls back to local Fernet encryption when Key Vault is not configured.
"""
import logging
import re
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

# Key Vault secret name prefix stored in DB to indicate KV-backed secret
KV_PREFIX = "kv://"

# Azure Key Vault only allows alphanumeric and dashes, 1-127 chars
_SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9-]")


def _sanitize_secret_name(name: str) -> str:
    """Convert an arbitrary name to a valid Key Vault secret name."""
    sanitized = _SAFE_NAME_RE.sub("-", name).strip("-")
    return sanitized[:127] if sanitized else "secret"


def is_keyvault_ref(value: str) -> bool:
    """Check if a stored value is a Key Vault reference."""
    return bool(value) and value.startswith(KV_PREFIX)


def _get_secret_name_from_ref(ref: str) -> str:
    """Extract the Key Vault secret name from a kv:// reference."""
    return ref[len(KV_PREFIX):]


class KeyVaultService:
    """Wrapper around Azure Key Vault SecretClient."""

    def __init__(self):
        self._client = None
        self._enabled = False
        self._vault_url = settings.AZURE_KEY_VAULT_URL

        if self._vault_url:
            try:
                from azure.identity import DefaultAzureCredential
                from azure.keyvault.secrets import SecretClient

                credential = DefaultAzureCredential()
                self._client = SecretClient(vault_url=self._vault_url, credential=credential)
                self._enabled = True
                logger.info("Azure Key Vault integration enabled: %s", self._vault_url)
            except ImportError:
                logger.warning(
                    "azure-keyvault-secrets or azure-identity not installed. "
                    "Key Vault integration disabled."
                )
            except Exception as e:
                logger.error("Failed to initialize Key Vault client: %s", e)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def store_secret(self, name: str, value: str) -> str:
        """Store a secret in Key Vault and return the kv:// reference.

        If Key Vault is not enabled, returns None so the caller can fall back
        to local encryption.
        """
        if not self._enabled or not self._client:
            return None
        try:
            safe_name = _sanitize_secret_name(name)
            self._client.set_secret(safe_name, value)
            logger.debug("Stored secret in Key Vault: %s", safe_name)
            return f"{KV_PREFIX}{safe_name}"
        except Exception as e:
            logger.error("Failed to store secret '%s' in Key Vault: %s", name, e)
            return None

    def get_secret(self, ref: str) -> Optional[str]:
        """Retrieve a secret from Key Vault by its kv:// reference."""
        if not self._enabled or not self._client:
            return None
        if not is_keyvault_ref(ref):
            return None
        try:
            secret_name = _get_secret_name_from_ref(ref)
            secret = self._client.get_secret(secret_name)
            return secret.value
        except Exception as e:
            logger.error("Failed to retrieve secret '%s' from Key Vault: %s", ref, e)
            return None

    def delete_secret(self, ref: str) -> bool:
        """Delete a secret from Key Vault by its kv:// reference."""
        if not self._enabled or not self._client:
            return False
        if not is_keyvault_ref(ref):
            return False
        try:
            secret_name = _get_secret_name_from_ref(ref)
            self._client.begin_delete_secret(secret_name)
            logger.debug("Deleted secret from Key Vault: %s", secret_name)
            return True
        except Exception as e:
            logger.error("Failed to delete secret '%s' from Key Vault: %s", ref, e)
            return False

    def test_connection(self) -> dict:
        """Test the Key Vault connection. Returns status dict."""
        if not self._vault_url:
            return {"connected": False, "error": "AZURE_KEY_VAULT_URL not configured"}
        if not self._enabled or not self._client:
            return {"connected": False, "error": "Key Vault client not initialized"}
        try:
            # List first page of secrets to test connectivity
            next(self._client.list_properties_of_secrets(max_page_size=1), None)
            return {"connected": True, "vault_url": self._vault_url}
        except Exception as e:
            return {"connected": False, "error": str(e)}


# Module-level singleton
keyvault_service = KeyVaultService()
