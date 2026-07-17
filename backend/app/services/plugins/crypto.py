"""Fernet encryption for stored OAuth tokens.

Set PLUGIN_TOKEN_KEY to your own 32-byte urlsafe base64 key in production
(generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())").
In dev, a stable key is derived from JWT_SECRET so things work out of the box.
"""

import base64
import hashlib
import logging

from cryptography.fernet import Fernet

from ...config import settings

log = logging.getLogger(__name__)
_fernet: Fernet | None = None


def _get() -> Fernet:
    global _fernet
    if _fernet is None:
        key = settings.PLUGIN_TOKEN_KEY
        if not key:
            log.warning("PLUGIN_TOKEN_KEY not set — deriving token key from JWT_SECRET (dev only)")
            key = base64.urlsafe_b64encode(hashlib.sha256(settings.JWT_SECRET.encode()).digest()).decode()
        _fernet = Fernet(key.encode() if isinstance(key, str) else key)
    return _fernet


def encrypt_token(token: str) -> str:
    return _get().encrypt(token.encode()).decode()


def decrypt_token(enc: str) -> str:
    return _get().decrypt(enc.encode()).decode()
