"""Тесты backend.security.twitch_oauth: OAuth-флоу Twitch с фейковым aiohttp.

Запуск:
    .venv\\Scripts\\python.exe -m pytest tests/test_twitch_oauth.py -q

Сеть не используется: aiohttp в модуле подменяется фейком.
"""
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

import backend.security.twitch_oauth as twitch_oauth
from backend.security.twitch_oauth import (
    TWITCH_TOKEN_URL,
    TWITCH_USERS_URL,
    build_authorize_url,
    exchange_code,
    fetch_twitch_user,
    refresh_access_token,
)

SETTINGS = SimpleNamespace(
    twitch_client_id="cid",
    twitch_client_secret="secret",
    twitch_redirect_uri="http://127.0.0.1:8001/api/v1/auth/callback",
    twitch_scope="user:read:email",
)


class _FakeResponse:
    def __init__(self, status: int, body: dict):
        self.status = status
        self._body = body

    async def json(self, content_type=None):
        return self._body

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeClient:
    """Мини-замена aiohttp.ClientSession с записью запросов."""

    last_instance = None

    def __init__(self, response: _FakeResponse):
        self._response = response
        self.post_calls = []
        self.get_calls = []
        _FakeClient.last_instance = self

    def post(self, url, data=None):
        self.post_calls.append((url, data))
        return self._response

    def get(self, url, headers=None):
        self.get_calls.append((url, headers))
        return self._response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setattr(twitch_oauth, "get_backend_settings", lambda: SETTINGS)


def _stub_http(monkeypatch, status: int, body: dict):
    response = _FakeResponse(status, body)

    def factory(*args, **kwargs):
        return _FakeClient(response)

    monkeypatch.setattr(
        twitch_oauth,
        "aiohttp",
        SimpleNamespace(ClientSession=factory, ClientTimeout=lambda total: None),
    )


# --- build_authorize_url ---


def test_build_authorize_url_contains_params():
    url = build_authorize_url("state123")
    parsed = urlparse(url)
    params = {k: v[0] for k, v in parse_qs(parsed.query).items()}

    assert url.startswith("https://id.twitch.tv/oauth2/authorize?")
    assert params == {
        "client_id": "cid",
        "redirect_uri": SETTINGS.twitch_redirect_uri,
        "response_type": "code",
        "scope": "user:read:email",
        "state": "state123",
    }


def test_build_authorize_url_custom_scope():
    params = parse_qs(urlparse(build_authorize_url("s", scope="a b")).query)
    assert params["scope"] == ["a b"]


# --- exchange_code ---


async def test_exchange_code_success(monkeypatch):
    _stub_http(monkeypatch, 200, {"access_token": "at", "refresh_token": "rt"})

    body = await exchange_code("code123")

    assert body == {"access_token": "at", "refresh_token": "rt"}
    url, data = _FakeClient.last_instance.post_calls[0]
    assert url == TWITCH_TOKEN_URL
    assert data["grant_type"] == "authorization_code"
    assert data["code"] == "code123"
    assert data["client_id"] == "cid"


async def test_exchange_code_error_raises(monkeypatch):
    _stub_http(monkeypatch, 400, {"message": "invalid code"})
    with pytest.raises(ValueError, match="invalid code"):
        await exchange_code("bad")


async def test_exchange_code_error_fallback_message(monkeypatch):
    _stub_http(monkeypatch, 500, {})
    with pytest.raises(ValueError, match="token exchange failed"):
        await exchange_code("code")


async def test_exchange_code_not_configured(monkeypatch):
    monkeypatch.setattr(
        twitch_oauth,
        "get_backend_settings",
        lambda: SimpleNamespace(
            twitch_client_id=None, twitch_client_secret=None, twitch_redirect_uri=None
        ),
    )
    with pytest.raises(RuntimeError, match="not configured"):
        await exchange_code("code")


# --- fetch_twitch_user ---


async def test_fetch_twitch_user_success(monkeypatch):
    _stub_http(monkeypatch, 200, {"data": [{"id": "123", "login": "tabula"}]})

    user = await fetch_twitch_user("token")

    assert user == {"id": "123", "login": "tabula"}
    url, headers = _FakeClient.last_instance.get_calls[0]
    assert url == TWITCH_USERS_URL
    assert headers["Authorization"] == "Bearer token"
    assert headers["Client-Id"] == "cid"


async def test_fetch_twitch_user_empty_data(monkeypatch):
    _stub_http(monkeypatch, 200, {"data": []})
    with pytest.raises(ValueError, match="no user"):
        await fetch_twitch_user("token")


async def test_fetch_twitch_user_error(monkeypatch):
    _stub_http(monkeypatch, 401, {"message": "unauthorized"})
    with pytest.raises(ValueError, match="unauthorized"):
        await fetch_twitch_user("token")


# --- refresh_access_token ---


async def test_refresh_success(monkeypatch):
    _stub_http(monkeypatch, 200, {"access_token": "new", "expires_in": 3600})

    body = await refresh_access_token("rt")

    assert body["access_token"] == "new"
    _url, data = _FakeClient.last_instance.post_calls[0]
    assert data["grant_type"] == "refresh_token"
    assert data["refresh_token"] == "rt"


async def test_refresh_without_access_token_raises(monkeypatch):
    _stub_http(monkeypatch, 200, {"expires_in": 3600})
    with pytest.raises(ValueError, match="no access token"):
        await refresh_access_token("rt")


async def test_refresh_error_raises(monkeypatch):
    _stub_http(monkeypatch, 400, {"error": "invalid_grant"})
    with pytest.raises(ValueError, match="invalid_grant"):
        await refresh_access_token("rt")


async def test_refresh_not_configured(monkeypatch):
    monkeypatch.setattr(
        twitch_oauth,
        "get_backend_settings",
        lambda: SimpleNamespace(twitch_client_id=None, twitch_client_secret=None),
    )
    with pytest.raises(RuntimeError, match="not configured"):
        await refresh_access_token("rt")
