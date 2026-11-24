"""Тесты backend.security.twitch_tokens: ротация токенов из БД.

Запуск:
    .venv\\Scripts\\python.exe -m pytest tests/test_twitch_tokens.py -q

БД и сеть подменяются фейками; шифрование — реальное (с тестовым ключом).
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet

import backend.security.twitch_tokens as twitch_tokens
from backend.security.token_crypto import decrypt_token
from backend.security.twitch_tokens import (
    get_streamer_access_token,
    get_twitch_access_token,
    _rotate,
)

VALID_KEY = Fernet.generate_key().decode()
SETTINGS = SimpleNamespace(
    token_encryption_key=VALID_KEY,
    twitch_token_refresh_skew_seconds=300,
)


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setattr(twitch_tokens, "get_backend_settings", lambda: SETTINGS)


class FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class FakeSession:
    def __init__(self, authorization=None):
        self._authorization = authorization
        self.flushed = False

    async def execute(self, *_args, **_kwargs):
        return FakeResult(self._authorization)

    async def flush(self):
        self.flushed = True


def _authorization(expires_at, access="old-access", refresh="old-refresh"):
    return SimpleNamespace(
        access_token_encrypted=(
            twitch_tokens.encrypt_token(access) if access else None
        ),
        refresh_token_encrypted=(
            twitch_tokens.encrypt_token(refresh) if refresh else None
        ),
        expires_at=expires_at,
        key_version=0,
        last_refresh_at=None,
        updated_at=None,
    )


# --- _rotate ---


async def test_rotate_returns_stored_token_when_fresh():
    auth = _authorization(datetime.utcnow() + timedelta(hours=1))
    session = FakeSession()

    token = await _rotate(session, auth)

    assert token == "old-access"
    assert not session.flushed


async def test_rotate_without_expiry_returns_stored_token():
    auth = _authorization(None)
    token = await _rotate(FakeSession(), auth)
    assert token == "old-access"


async def test_rotate_within_skew_refreshes(monkeypatch):
    calls = []

    async def fake_refresh(refresh_token):
        calls.append(refresh_token)
        return {"access_token": "new-access", "refresh_token": "new-refresh", "expires_in": 3600}

    monkeypatch.setattr(twitch_tokens, "refresh_access_token", fake_refresh)

    # Истекает через минуту — внутри skew (300 с), нужна ротация.
    auth = _authorization(datetime.utcnow() + timedelta(minutes=1))
    session = FakeSession()

    token = await _rotate(session, auth)

    assert token == "new-access"
    assert calls == ["old-refresh"]
    assert session.flushed
    assert decrypt_token(auth.access_token_encrypted) == "new-access"
    assert decrypt_token(auth.refresh_token_encrypted) == "new-refresh"
    assert auth.key_version == twitch_tokens.KEY_VERSION
    assert auth.expires_at is not None
    assert auth.last_refresh_at is not None


async def test_rotate_keeps_old_refresh_when_response_has_none(monkeypatch):
    async def fake_refresh(_token):
        return {"access_token": "new-access", "expires_in": 3600}

    monkeypatch.setattr(twitch_tokens, "refresh_access_token", fake_refresh)

    auth = _authorization(datetime.utcnow() - timedelta(minutes=1))
    await _rotate(FakeSession(), auth)

    assert decrypt_token(auth.refresh_token_encrypted) == "old-refresh"


async def test_rotate_expired_sets_no_expiry_without_expires_in(monkeypatch):
    async def fake_refresh(_token):
        return {"access_token": "new-access"}

    monkeypatch.setattr(twitch_tokens, "refresh_access_token", fake_refresh)

    auth = _authorization(datetime.utcnow() - timedelta(minutes=1))
    await _rotate(FakeSession(), auth)

    assert auth.expires_at is None


async def test_rotate_without_access_token_raises():
    auth = _authorization(None, access=None)
    with pytest.raises(RuntimeError, match="access token is not available"):
        await _rotate(FakeSession(), auth)


async def test_rotate_without_refresh_token_raises():
    auth = _authorization(datetime.utcnow() - timedelta(hours=1))
    auth.refresh_token_encrypted = None
    with pytest.raises(RuntimeError, match="refresh token is not available"):
        await _rotate(FakeSession(), auth)


# --- get_twitch_access_token / get_streamer_access_token ---


async def test_get_twitch_access_token_missing_row():
    session = FakeSession(authorization=None)
    with pytest.raises(LookupError, match="Twitch authorization not found"):
        await get_twitch_access_token(session, user_id=1)


async def test_get_streamer_access_token_missing_row():
    session = FakeSession(authorization=None)
    with pytest.raises(LookupError, match="Streamer Twitch authorization not found"):
        await get_streamer_access_token(session, user_id=1)


async def test_get_twitch_access_token_returns_rotated():
    auth = _authorization(datetime.utcnow() + timedelta(hours=1))
    session = FakeSession(authorization=auth)

    assert await get_twitch_access_token(session, user_id=1) == "old-access"


async def test_get_streamer_access_token_returns_rotated():
    auth = _authorization(datetime.utcnow() + timedelta(hours=1))
    session = FakeSession(authorization=auth)

    assert await get_streamer_access_token(session, user_id=1) == "old-access"
