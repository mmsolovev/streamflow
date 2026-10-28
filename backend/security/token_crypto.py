"""Шифрование OAuth-токенов Twitch в БД."""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from backend.config import get_backend_settings


CIPHER_PREFIX = "v1:"
KEY_VERSION = 1


def _fernet() -> Fernet:
    key = (get_backend_settings().token_encryption_key or "").strip()
    if not key:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY is not configured")
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as exc:
        raise RuntimeError("TOKEN_ENCRYPTION_KEY is invalid") from exc


def encrypt_token(value: str) -> str:
    if not value:
        raise ValueError("Cannot encrypt an empty token")
    return CIPHER_PREFIX + _fernet().encrypt(value.encode()).decode()


def decrypt_token(value: str) -> str:
    if not value:
        raise ValueError("Cannot decrypt an empty token")
    if not value.startswith(CIPHER_PREFIX):
        raise ValueError("Unknown token cipher version")
    try:
        return _fernet().decrypt(value[len(CIPHER_PREFIX) :].encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Unable to decrypt token") from exc


def decrypt_stored_token(encrypted: str | None) -> str | None:
    return decrypt_token(encrypted) if encrypted else None
