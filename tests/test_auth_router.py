"""Тесты backend.routers.auth: OAuth-флоу, upsert пользователя, logout.

Запуск:
    .venv\\Scripts\\python.exe -m pytest tests/test_auth_router.py -q

Роутер-функции вызываются напрямую; внешние зависимости (Twitch API,
шифрование, куки, бан-синк) подменяются фейками.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException, Response
from fastapi.responses import RedirectResponse

import backend.routers.auth as auth
import backend.security.sessions as sessions_mod
import backend.security.token_crypto as token_crypto_mod
import services.twitch_ban_service as twitch_ban_service
from backend.schemas.auth import UserView
from backend.security.sessions import IssuedSession
from database.models import TwitchAuthorization, TwitchStreamerAuthorization, User, UserProfile, WebSession

VALID_KEY = Fernet.generate_key().decode()

TWITCH_USER = {"id": "123", "login": "viewer", "display_name": "Viewer"}
TOKEN_DATA = {
    "access_token": "at-1",
    "refresh_token": "rt-1",
    "expires_in": 3600,
    "scope": ["user:read:email"],
}


def _settings(**overrides):
    base = dict(
        twitch_client_id="cid",
        twitch_client_secret="secret",
        twitch_redirect_uri="http://test/api/v1/auth/callback",
        backend_oauth_state_cookie_name="backend_oauth_state",
        backend_cookie_name="backend_session_id",
        backend_csrf_cookie_name="backend_csrf_token",
        backend_cookie_secure=False,
        backend_session_ttl_days=30,
        backend_session_idle_minutes=60,
        twitch_oauth_state_ttl_seconds=600,
        backend_frontend_url=None,
        twitch_streamer_scopes=["channel:read:redemptions"],
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class FakeResult:
    def __init__(self, value=None, rows=None):
        self._value = value
        self._rows = rows or []

    def scalar_one_or_none(self):
        return self._value

    def scalars(self):
        return self

    def all(self):
        return self._rows


class FakeAuthSession:
    """execute() отдаёт результаты из очереди, get() — из словаря."""

    def __init__(self, results=None, gets=None):
        self._results = list(results or [])
        self._gets = dict(gets or {})
        self.added = []
        self.deleted = []
        self.committed = False
        self.rolled_back = False
        self._next_id = 100

    async def execute(self, *_args, **_kwargs):
        if self._results:
            return self._results.pop(0)
        return FakeResult(None)

    async def get(self, model, pk):
        return self._gets.get(model)

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = self._next_id
                self._next_id += 1

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True

    async def delete(self, obj):
        self.deleted.append(obj)


@pytest.fixture(autouse=True)
def env(monkeypatch):
    """Общий фейк-настройки для auth/sessions/token_crypto + заглушки."""
    settings = _settings()
    monkeypatch.setattr(auth, "get_backend_settings", lambda: settings)
    monkeypatch.setattr(sessions_mod, "get_backend_settings", lambda: settings)
    monkeypatch.setattr(
        token_crypto_mod,
        "get_backend_settings",
        lambda: SimpleNamespace(token_encryption_key=VALID_KEY),
    )
    # apply_owner_bootstrap зависит от OWNER_* в .env — изолируем.
    monkeypatch.setattr(auth, "apply_owner_bootstrap", lambda user, login=None: False)
    monkeypatch.setattr(auth, "STREAMER_LOGINS", {"tabula"})

    async def _no_ban(*args, **kwargs):
        return SimpleNamespace(twitch_banned=False, service_banned=False)

    monkeypatch.setattr(twitch_ban_service, "sync_user_twitch_ban", _no_ban)
    return settings


def _request(cookies=None):
    return SimpleNamespace(cookies=cookies or {})


# --- чистые хелперы ---


def test_frontend_redirect_with_merges_params():
    assert (
        auth._frontend_redirect_with("http://fe:5173/", login="success")
        == "http://fe:5173/?login=success"
    )
    # Существующий query сохраняется.
    assert (
        auth._frontend_redirect_with("http://fe/?a=1", b="2") == "http://fe/?a=1&b=2"
    )


def test_new_oauth_state_has_flow_prefix():
    state = auth._new_oauth_state("login")
    assert state.startswith("login.")
    assert len(state) > len("login.") + 20


def test_oauth_state_flow():
    assert auth._oauth_state_flow("login.abc") == "login"
    assert auth._oauth_state_flow("streamer.xyz") == "streamer"
    assert auth._oauth_state_flow("evil.xyz") is None
    assert auth._oauth_state_flow("nopoint") is None
    assert auth._oauth_state_flow(None) is None
    assert auth._oauth_state_flow("") is None


@pytest.mark.parametrize(
    ("scopes", "expected"),
    [
        ("a b", "a b"),
        (["a", "b"], "a b"),
        (("a",), "a"),
        (None, ""),
        (42, ""),
    ],
)
def test_scopes_string(scopes, expected):
    assert auth._scopes_string(scopes) == expected


def test_oauth_error_shape():
    exc = auth._oauth_error("msg", "code")
    assert exc.status_code == 400
    assert exc.detail == {"code": "code", "message": "msg"}


def test_user_view_without_actor():
    user = User(id=1, twitch_user_id="1", role="admin", is_streamer=False)
    view = auth._user_view(user, "viewer", "Viewer")
    assert isinstance(view, UserView)
    assert view.role == "admin"
    # display_role скрывает точную роль staff от клиента.
    assert view.display_role == "admin"
    assert view.login == "viewer"
    assert view.can_write is False


def test_user_view_hides_unknown_login():
    user = User(id=1, twitch_user_id="1", role="user", is_streamer=False)
    view = auth._user_view(user, "unknown", "unknown")
    assert view.login is None
    assert view.display_name is None


# --- _upsert_twitch_user ---


async def test_upsert_creates_user_and_profile():
    session = FakeAuthSession()

    user, login, display_name = await auth._upsert_twitch_user(session, TWITCH_USER)

    assert login == "viewer"
    assert display_name == "Viewer"
    assert user.id == 100  # выдан фейковым flush
    assert user.twitch_user_id == "123"
    assert user.role == "user"
    assert user.is_streamer is False

    profiles = [obj for obj in session.added if isinstance(obj, UserProfile)]
    assert len(profiles) == 1
    assert profiles[0].login == "viewer"
    assert profiles[0].twitch_url == "https://twitch.tv/viewer"


async def test_upsert_marks_streamer_login(env):
    session = FakeAuthSession()
    twitch_user = dict(TWITCH_USER, login="tabula", display_name="Tabula")

    user, login, _ = await auth._upsert_twitch_user(session, twitch_user)

    assert login == "tabula"
    assert user.is_streamer is True


async def test_upsert_reuses_existing_user_and_profile():
    user = User(id=5, twitch_user_id="123", role="editor", is_streamer=False)
    profile = UserProfile(user_id=5, is_current=True, login="old", display_name="Old")
    session = FakeAuthSession(results=[FakeResult(user), FakeResult(profile)])

    result_user, login, _ = await auth._upsert_twitch_user(session, TWITCH_USER)

    assert result_user is user
    assert login == "viewer"
    assert profile.login == "viewer"
    assert profile.display_name == "Viewer"
    # Существующий пользователь не добавляется повторно.
    assert user not in session.added


@pytest.mark.parametrize(
    "payload",
    [
        {"id": "", "login": "viewer"},
        {"id": "123", "login": ""},
        {},
    ],
)
async def test_upsert_incomplete_profile_rejected(payload):
    session = FakeAuthSession()
    with pytest.raises(HTTPException) as exc_info:
        await auth._upsert_twitch_user(session, payload)
    assert exc_info.value.detail["code"] == "invalid_twitch_user"


# --- _store_login_authorization ---


async def test_store_login_authorization_creates_row():
    user = User(id=5, twitch_user_id="123", role="user")
    session = FakeAuthSession()

    await auth._store_login_authorization(session, user, TOKEN_DATA)

    rows = [obj for obj in session.added if isinstance(obj, TwitchAuthorization)]
    assert len(rows) == 1
    row = rows[0]
    assert row.user_id == 5
    assert token_crypto_mod.decrypt_token(row.access_token_encrypted) == "at-1"
    assert token_crypto_mod.decrypt_token(row.refresh_token_encrypted) == "rt-1"
    assert row.scopes == "user:read:email"
    assert row.expires_at is not None


async def test_store_login_authorization_updates_existing_row():
    user = User(id=5, twitch_user_id="123", role="user")
    existing = TwitchAuthorization(user_id=5, created_at=datetime.utcnow())
    session = FakeAuthSession(gets={TwitchAuthorization: existing})

    await auth._store_login_authorization(session, user, TOKEN_DATA)

    assert existing not in session.added
    assert token_crypto_mod.decrypt_token(existing.access_token_encrypted) == "at-1"


async def test_store_login_authorization_reuses_stored_refresh():
    user = User(id=5, twitch_user_id="123", role="user")
    existing = TwitchAuthorization(user_id=5, created_at=datetime.utcnow())
    existing.refresh_token_encrypted = token_crypto_mod.encrypt_token("old-rt")
    session = FakeAuthSession(gets={TwitchAuthorization: existing})

    # Twitch не вернул refresh_token (offline-скоуп не запрашивался повторно).
    await auth._store_login_authorization(session, user, {"access_token": "at-2"})

    assert token_crypto_mod.decrypt_token(existing.refresh_token_encrypted) == "old-rt"
    assert existing.expires_at is None


async def test_store_login_authorization_without_refresh_raises():
    user = User(id=5, twitch_user_id="123", role="user")
    session = FakeAuthSession()

    with pytest.raises(ValueError, match="refresh token"):
        await auth._store_login_authorization(session, user, {"access_token": "at"})


# --- callback ---


def _stub_oauth(monkeypatch, token_data=None, twitch_user=None):
    async def _exchange(code):
        return token_data if token_data is not None else TOKEN_DATA

    async def _fetch(token):
        return twitch_user if twitch_user is not None else TWITCH_USER

    monkeypatch.setattr(auth, "exchange_code", _exchange)
    monkeypatch.setattr(auth, "fetch_twitch_user", _fetch)
    monkeypatch.setattr(
        auth,
        "create_session",
        lambda session, user_id: _async_issued(user_id),
    )


async def _async_issued(user_id):
    return IssuedSession(web_session=None, token="tok", csrf_token="csrf")


async def _callback(monkeypatch, *, state="login.abc", cookies=None, **kwargs):
    _stub_oauth(monkeypatch)
    request = _request({"backend_oauth_state": state, **(cookies or {})})
    return await auth.callback(
        request=request,
        response=Response(),
        session=kwargs.pop("session", FakeAuthSession()),
        code=kwargs.pop("code", "code1"),
        state=state,
        error=kwargs.pop("error", None),
    )


async def test_callback_login_success_returns_user_view(monkeypatch):
    session = FakeAuthSession()
    result = await _callback(monkeypatch, session=session)

    assert isinstance(result, UserView)
    assert result.login == "viewer"
    assert result.role == "user"
    assert session.committed
    # Токены сохранены в БД.
    assert any(isinstance(obj, TwitchAuthorization) for obj in session.added)


async def test_callback_sets_session_and_csrf_cookies(monkeypatch):
    response = Response()
    _stub_oauth(monkeypatch)

    await auth.callback(
        request=_request({"backend_oauth_state": "login.abc"}),
        response=response,
        session=FakeAuthSession(),
        code="code1",
        state="login.abc",
        error=None,
    )

    cookies = response.headers.getlist("set-cookie")
    joined = "\n".join(cookies)
    assert "backend_session_id=tok" in joined
    assert "backend_csrf_token=csrf" in joined
    # State-кука удаляется.
    assert any(
        "backend_oauth_state=" in item and ('Max-Age=0' in item or "expires=" in item.lower())
        for item in cookies
    )


async def test_callback_frontend_redirect(env, monkeypatch):
    env.backend_frontend_url = "http://fe:5173/"

    result = await _callback(monkeypatch)

    assert isinstance(result, RedirectResponse)
    assert result.status_code == 303
    assert result.headers["location"] == "http://fe:5173/?login=success"


async def test_callback_error_param(monkeypatch):
    with pytest.raises(HTTPException) as exc_info:
        await _callback(monkeypatch, error="access_denied")
    assert "access_denied" in exc_info.value.detail["message"]


async def test_callback_state_mismatch(monkeypatch):
    with pytest.raises(HTTPException) as exc_info:
        await _callback(monkeypatch, state="login.abc", cookies={"backend_oauth_state": "login.other"})
    assert exc_info.value.detail["code"] == "invalid_oauth_state"


async def test_callback_missing_state_cookie(monkeypatch):
    _stub_oauth(monkeypatch)
    with pytest.raises(HTTPException) as exc_info:
        await auth.callback(
            request=_request({}),
            response=Response(),
            session=FakeAuthSession(),
            code="c",
            state="login.abc",
            error=None,
        )
    assert exc_info.value.detail["code"] == "invalid_oauth_state"


async def test_callback_exchange_value_error_maps_400(monkeypatch):
    async def _exchange(code):
        raise ValueError("invalid code")

    monkeypatch.setattr(auth, "exchange_code", _exchange)
    session = FakeAuthSession()

    with pytest.raises(HTTPException) as exc_info:
        await auth.callback(
            request=_request({"backend_oauth_state": "login.abc"}),
            response=Response(),
            session=session,
            code="c",
            state="login.abc",
            error=None,
        )
    assert exc_info.value.status_code == 400
    assert session.rolled_back


async def test_callback_not_configured_maps_400(monkeypatch):
    async def _exchange(code):
        raise RuntimeError("Twitch OAuth is not configured")

    monkeypatch.setattr(auth, "exchange_code", _exchange)

    with pytest.raises(HTTPException) as exc_info:
        await auth.callback(
            request=_request({"backend_oauth_state": "login.abc"}),
            response=Response(),
            session=FakeAuthSession(),
            code="c",
            state="login.abc",
            error=None,
        )
    assert exc_info.value.detail["code"] == "oauth_not_configured"


async def test_callback_provider_error_maps_502(monkeypatch):
    async def _exchange(code):
        raise ConnectionError("network down")

    monkeypatch.setattr(auth, "exchange_code", _exchange)

    with pytest.raises(HTTPException) as exc_info:
        await auth.callback(
            request=_request({"backend_oauth_state": "login.abc"}),
            response=Response(),
            session=FakeAuthSession(),
            code="c",
            state="login.abc",
            error=None,
        )
    assert exc_info.value.status_code == 502
    assert exc_info.value.detail["code"] == "oauth_provider_error"


async def test_callback_incomplete_twitch_user_rolls_back(monkeypatch):
    _stub_oauth(monkeypatch, twitch_user={"id": "", "login": ""})
    session = FakeAuthSession()

    with pytest.raises(HTTPException) as exc_info:
        await auth.callback(
            request=_request({"backend_oauth_state": "login.abc"}),
            response=Response(),
            session=session,
            code="c",
            state="login.abc",
            error=None,
        )
    assert exc_info.value.detail["code"] == "invalid_twitch_user"
    assert session.rolled_back


# --- callback: стримерский флоу ---


async def test_callback_streamer_flow_denied_for_regular_user(monkeypatch):
    _stub_oauth(monkeypatch)
    session = FakeAuthSession()

    with pytest.raises(HTTPException) as exc_info:
        await auth.callback(
            request=_request({"backend_oauth_state": "streamer.abc"}),
            response=Response(),
            session=session,
            code="c",
            state="streamer.abc",
            error=None,
        )
    assert exc_info.value.detail["code"] == "streamer_not_allowed"
    assert session.rolled_back


async def test_callback_streamer_flow_denied_redirects_frontend(env, monkeypatch):
    env.backend_frontend_url = "http://fe:5173/"

    async def _exchange(code):
        return TOKEN_DATA

    async def _fetch(token):
        return TWITCH_USER

    monkeypatch.setattr(auth, "exchange_code", _exchange)
    monkeypatch.setattr(auth, "fetch_twitch_user", _fetch)

    result = await auth.callback(
        request=_request({"backend_oauth_state": "streamer.abc"}),
        response=Response(),
        session=FakeAuthSession(),
        code="c",
        state="streamer.abc",
        error=None,
    )

    assert isinstance(result, RedirectResponse)
    assert result.headers["location"] == "http://fe:5173/?streamer=denied"


async def test_callback_streamer_flow_allowed_for_streamer_login(monkeypatch):
    async def _exchange(code):
        return TOKEN_DATA

    async def _fetch(token):
        return dict(TWITCH_USER, login="tabula", display_name="Tabula")

    monkeypatch.setattr(auth, "exchange_code", _exchange)
    monkeypatch.setattr(auth, "fetch_twitch_user", _fetch)
    session = FakeAuthSession()

    result = await auth.callback(
        request=_request({"backend_oauth_state": "streamer.abc"}),
        response=Response(),
        session=session,
        code="c",
        state="streamer.abc",
        error=None,
    )

    assert isinstance(result, UserView)
    assert result.login == "tabula"
    assert session.committed
    rows = [obj for obj in session.added if isinstance(obj, TwitchStreamerAuthorization)]
    assert len(rows) == 1
    assert rows[0].twitch_login == "tabula"
    assert token_crypto_mod.decrypt_token(rows[0].access_token_encrypted) == "at-1"


# --- streamer_status ---


async def test_streamer_status_lists_logins(env):
    row = TwitchStreamerAuthorization(user_id=1, twitch_login="tabula", scopes="a b")
    row.expires_at = datetime.utcnow() + timedelta(days=1)
    session = FakeAuthSession(results=[FakeResult(rows=[row])])

    status = await auth.streamer_status(session=session, _admin=object())

    assert status.requested_scopes == env.twitch_streamer_scopes
    assert len(status.streamers) == 1
    view = status.streamers[0]
    assert view.login == "tabula"
    assert view.connected is True
    assert view.scopes == "a b"


async def test_streamer_status_not_connected():
    session = FakeAuthSession(results=[FakeResult(rows=[])])

    status = await auth.streamer_status(session=session, _admin=object())

    assert status.streamers[0].connected is False
    assert status.streamers[0].scopes is None


# --- logout ---


async def test_logout_deletes_web_session(env):
    web_session = WebSession(
        user_id=1,
        token_hash=sessions_mod.hash_secret("tok"),
        csrf_hash="x",
        created_at=datetime.utcnow(),
        last_activity_at=datetime.utcnow(),
        expires_at=datetime.utcnow() + timedelta(hours=1),
    )
    session = FakeAuthSession(results=[FakeResult(web_session)])
    response = Response()

    result = await auth.logout(
        request=_request({"backend_session_id": "tok"}),
        response=response,
        session=session,
        _user=SimpleNamespace(id=1),
    )

    assert result.status_code == 204
    assert session.deleted == [web_session]
    assert session.committed


async def test_logout_without_cookie_still_clears():
    session = FakeAuthSession()
    response = Response()

    result = await auth.logout(
        request=_request({}),
        response=response,
        session=session,
        _user=SimpleNamespace(id=1),
    )

    assert result.status_code == 204
    assert not session.committed
    joined = "\n".join(response.headers.getlist("set-cookie"))
    assert "backend_session_id=" in joined
    assert "backend_csrf_token=" in joined
