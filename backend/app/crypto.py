"""Encryption of provider secrets stored in the database (LDAP bind password, OIDC client secret).

Key: LODESTONE_ENCRYPTION_KEY if set, otherwise derived from LODESTONE_SECRET_KEY. Changing the key makes stored
secrets unreadable: they have to be entered again in the admin UI.
"""
import base64
import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken

from .config import get_settings


def _fernet() -> Fernet:
    s = get_settings()
    raw = s.encryption_key or s.secret_key
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(b"lodestone-secrets:" + raw.encode()).digest()))


def encrypt(data: dict) -> str | None:
    clean = {k: v for k, v in data.items() if v}
    return _fernet().encrypt(json.dumps(clean).encode()).decode() if clean else None


def decrypt(token: str | None) -> dict:
    if not token:
        return {}
    try:
        return json.loads(_fernet().decrypt(token.encode()))
    except InvalidToken:
        return {}
