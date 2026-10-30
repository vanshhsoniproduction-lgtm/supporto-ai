import base64
import hashlib
from django.conf import settings
from cryptography.fernet import Fernet

def _get_fernet_key() -> bytes:
    """Derive a reproducible 32-byte urlsafe base64-encoded key from SECRET_KEY."""
    raw_secret = getattr(settings, "ENCRYPTION_KEY", None) or settings.SECRET_KEY
    key_32 = hashlib.sha256(raw_secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(key_32)

def encrypt_token(token: str) -> str:
    """Encrypts a sensitive string token returning a base64 ciphertext string."""
    if not token:
        return ""
    f = Fernet(_get_fernet_key())
    encrypted = f.encrypt(token.encode("utf-8"))
    return encrypted.decode("utf-8")

def decrypt_token(encrypted_token: str) -> str:
    """Decrypts a previously encrypted token string."""
    if not encrypted_token:
        return ""
    try:
        f = Fernet(_get_fernet_key())
        decrypted = f.decrypt(encrypted_token.encode("utf-8"))
        return decrypted.decode("utf-8")
    except Exception:
        return ""

