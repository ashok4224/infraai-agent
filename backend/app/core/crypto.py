import base64
import hashlib
import uuid
from cryptography.fernet import Fernet
from app.config import settings

from sqlalchemy.types import TypeDecorator, Text

# Use dedicated ENCRYPTION_KEY if set, otherwise fall back to SECRET_KEY
_raw_key = settings.ENCRYPTION_KEY or settings.SECRET_KEY
_key_bytes = hashlib.sha256(_raw_key.encode()).digest()
_fernet = Fernet(base64.urlsafe_b64encode(_key_bytes))

# Lazy import to avoid circular dependency at module load time
_keyvault = None


def _get_keyvault():
    """Lazy-load the Key Vault service singleton."""
    global _keyvault
    if _keyvault is None:
        from app.services.keyvault_service import keyvault_service
        _keyvault = keyvault_service
    return _keyvault


def is_encrypted(text: str) -> bool:
    """Check if a string appears to be a Fernet token."""
    if not text:
        return False
    # Fernet tokens start with gAAAAA
    return str(text).startswith("gAAAAA")

def encrypt_string(plain_text: str, kv_name_hint: str | None = None) -> str:
    """Encrypt a string.

    If Key Vault is enabled, stores the secret there and returns a kv:// reference.
    Otherwise falls back to Fernet encryption.
    """
    if not plain_text:
        return plain_text
    if is_encrypted(plain_text):
        return plain_text  # Prevent double encryption

    kv = _get_keyvault()
    if kv and kv.enabled:
        from app.services.keyvault_service import is_keyvault_ref
        if is_keyvault_ref(plain_text):
            return plain_text  # Already a KV reference
        secret_name = kv_name_hint or f"infraai-{uuid.uuid4().hex[:12]}"
        ref = kv.store_secret(secret_name, plain_text)
        if ref:
            return ref
        # Fall through to Fernet if KV store failed

    return _fernet.encrypt(plain_text.encode()).decode()

def decrypt_string(encrypted_text: str) -> str:
    """Decrypt a string.

    Handles both Key Vault references (kv://) and Fernet tokens.
    """
    if not encrypted_text:
        return encrypted_text

    # Check for Key Vault reference first
    kv = _get_keyvault()
    if kv and kv.enabled:
        from app.services.keyvault_service import is_keyvault_ref
        if is_keyvault_ref(encrypted_text):
            value = kv.get_secret(encrypted_text)
            if value is not None:
                return value
            # If KV retrieval fails, return masked value
            return "••••••••"

    if not is_encrypted(encrypted_text):
        return encrypted_text
    try:
        return _fernet.decrypt(encrypted_text.encode()).decode()
    except Exception:
        # Fallback for existing plaintext passwords if any
        return encrypted_text

class EncryptedString(TypeDecorator):
    """SQLAlchemy type that transparently encrypts/decrypts strings.

    When Key Vault is enabled, stores a kv:// reference in the DB column.
    When disabled, stores a Fernet-encrypted token.
    """
    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return encrypt_string(str(value))

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return decrypt_string(str(value))

