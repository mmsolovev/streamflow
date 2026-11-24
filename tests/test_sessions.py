"""Тесты backend.security.sessions: хэш токенов, создание сессии, куки.

Запуск:
    .venv\\Scripts\\python.exe -m pytest tests/test_sessions.py -q
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

import backend.security.sessions as sessions
from backend.security.sessions import (
    IssuedSession,
    attach_csrf_cookie,
    attach_oauth_state_cookie,
    attach_session_cookie,
    clear_csrf_cookie,
    clear_oauth_state_cookie,
    clear_session_cookie,
    create_session,
    hash_secret,
)

SETTINGS = SimpleNamespace(
    backend_cookie_name="backend_session_id",
    backend_cookie_secure=False,
    backend_session_ttl_days=30,
    backend_session_idle_minutes=60,
    backend_oauth_state_cookie_name="backend_oauth_state",
    backend_csrf_cookie_name="backend_csrf_token",
    twitch_oauth_state_ttl_seconds=600,
)


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setattr(sessions, "get_backend_settings", lambda: SETTINGS)


class FakeResponse:
    def __init__(self):
        self.cookies_set = []
        self.cookies_deleted = []

    def set_cookie(self, **kwargs):
        self.cookies_set.append(kwargs)

    def delete_cookie(self, key, **kwargs):
        self.cookies_deleted.append((key, kwargs))


class FakeSession:
    def __init__(self):
        self.added = []
        self.flushed = False

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushed = True


# --- hash_secret ---


def test_hash_secret_is_sha256_hex():
    digest = hash_secret("abc")
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


def test_hash_secret_deterministic():
    assert hash_secret("token") == hash_secret("token")
    assert hash_secret("token") != hash_secret("token2")


# --- create_session ---


async def test_create_session_stores_hashes_not_tokens():
    db = FakeSession()
    issued = await create_session(db, user_id=42)

    assert db.flushed
    assert len(db.added) == 1
    row = db.added[0]

    assert row.user_id == 42
    assert row.token_hash == hash_secret(issued.token)
    assert row.csrf_hash == hash_secret(issued.csrf_token)
    # Сами токены в БД не хранятся.
    assert issued.token not in (row.token_hash, row.csrf_hash)
    assert issued.token != issued.csrf_token


async def test_create_session_expiry_uses_settings():
    db = FakeSession()
    issued = await create_session(db, user_id=1)
    row = issued.web_session

    idle = timedelta(minutes=SETTINGS.backend_session_idle_minutes)
    absolute = timedelta(days=SETTINGS.backend_session_ttl_days)
    assert row.expires_at - row.created_at == idle
    assert row.absolute_expires_at - row.created_at == absolute
    assert row.last_activity_at == row.created_at
    assert isinstance(row.created_at, datetime)


# --- куки ---


def test_attach_session_cookie_attributes():
    response = FakeResponse()
    issued = IssuedSession(web_session=None, token="tok", csrf_token="csrf")

    attach_session_cookie(response, issued)

    cookie = response.cookies_set[0]
    assert cookie["key"] == "backend_session_id"
    assert cookie["value"] == "tok"
    assert cookie["httponly"] is True
    assert cookie["samesite"] == "lax"
    assert cookie["max_age"] == 30 * 24 * 3600
    assert cookie["path"] == "/"


def test_attach_csrf_cookie_is_readable_by_js():
    response = FakeResponse()
    issued = IssuedSession(web_session=None, token="tok", csrf_token="csrf")

    attach_csrf_cookie(response, issued)

    cookie = response.cookies_set[0]
    assert cookie["key"] == "backend_csrf_token"
    assert cookie["value"] == "csrf"
    # CSRF-токен читается фронтендом — не HttpOnly.
    assert cookie["httponly"] is False


def test_attach_oauth_state_cookie_ttl():
    response = FakeResponse()
    attach_oauth_state_cookie(response, "state123")

    cookie = response.cookies_set[0]
    assert cookie["key"] == "backend_oauth_state"
    assert cookie["value"] == "state123"
    assert cookie["httponly"] is True
    assert cookie["max_age"] == 600


def test_clear_cookies():
    response = FakeResponse()
    clear_session_cookie(response)
    clear_csrf_cookie(response)
    clear_oauth_state_cookie(response)

    assert [key for key, _ in response.cookies_deleted] == [
        "backend_session_id",
        "backend_csrf_token",
        "backend_oauth_state",
    ]
    assert all(kwargs["path"] == "/" for _, kwargs in response.cookies_deleted)
