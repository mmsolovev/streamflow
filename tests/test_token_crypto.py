"""Тесты backend.security.token_crypto: шифрование токенов Fernet.

Запуск:
    .venv\\Scripts\\python.exe -m pytest tests/test_token_crypto.py -q
"""
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

import backend.security.token_crypto as token_crypto
from backend.security.token_crypto import (
    CIPHER_PREFIX,
    decrypt_stored_token,
    decrypt_token,
    encrypt_token,
)

VALID_KEY = Fernet.generate_key().decode()


@pytest.fixture(autouse=True)
def settings(monkeypatch):
    def _patch(key):
        monkeypatch.setattr(
            token_crypto,
            "get_backend_settings",
            lambda: SimpleNamespace(token_encryption_key=key),
        )

    _patch(VALID_KEY)
    return _patch


def test_roundtrip():
    encrypted = encrypt_token("secret-token")
    assert encrypted.startswith(CIPHER_PREFIX)
    assert encrypted != "secret-token"
    assert decrypt_token(encrypted) == "secret-token"


def test_unicode_roundtrip():
    assert decrypt_token(encrypt_token("токен-юникод-🔐")) == "токен-юникод-🔐"


def test_encrypt_empty_raises():
    with pytest.raises(ValueError, match="empty token"):
        encrypt_token("")


def test_decrypt_empty_raises():
    with pytest.raises(ValueError, match="empty token"):
        decrypt_token("")


def test_decrypt_unknown_version_raises():
    with pytest.raises(ValueError, match="cipher version"):
        decrypt_token("v0:something")


def test_decrypt_corrupted_raises():
    with pytest.raises(ValueError, match="Unable to decrypt"):
        decrypt_token(CIPHER_PREFIX + Fernet.generate_key().decode()[:40])


def test_decrypt_with_other_key_raises(settings):
    encrypted = encrypt_token("token")
    settings(Fernet.generate_key().decode())
    with pytest.raises(ValueError, match="Unable to decrypt"):
        decrypt_token(encrypted)


def test_decrypt_stored_token_none():
    assert decrypt_stored_token(None) is None
    assert decrypt_stored_token("") is None


def test_missing_key_raises(settings):
    settings(None)
    with pytest.raises(RuntimeError, match="not configured"):
        encrypt_token("x")

    settings("   ")
    with pytest.raises(RuntimeError, match="not configured"):
        encrypt_token("x")


def test_invalid_key_raises(settings):
    settings("not-a-valid-fernet-key")
    with pytest.raises(RuntimeError, match="invalid"):
        encrypt_token("x")
