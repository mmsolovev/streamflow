"""Security-sensitive tests for cookie session resolution and authorization.

No database or Twitch calls are made; the session/restriction services are
replaced with narrow fakes while the real CSRF and expiry decisions run.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import backend.deps as deps
from backend.app import app
from backend.security.sessions import hash_secret
from database.models import User
from services.authz_service import Actor, Capability, Restrictions, Role


SETTINGS = SimpleNamespace(
    backend_cookie_name="backend_session_id",
    backend_csrf_cookie_name="backend_csrf_token",
    backend_session_idle_minutes=60,
    owner_twitch_user_id=None,
    owner_twitch_login=None,
)


class FakeSession:
    def __init__(self, web_session=None, user=None):
        self.web_session = web_session
        self.user = user
        self.deleted = []
        self.committed = False
        self.flushed = False

    async def execute(self, _statement):
        return SimpleNamespace(scalar_one_or_none=lambda: self.web_session)

    async def get(self, model, user_id, **_kwargs):
        return self.user

    async def delete(self, obj):
        self.deleted.append(obj)

    async def commit(self):
        self.committed = True

    async def flush(self):
        self.flushed = True


def _web_session(*, expires_at=None, absolute_expires_at=None, csrf="csrf"):
    now = datetime.utcnow()
    return SimpleNamespace(
        user_id=17,
        token_hash=hash_secret("session-token"),
        csrf_hash=hash_secret(csrf) if csrf is not None else None,
        expires_at=expires_at or now + timedelta(hours=1),
        absolute_expires_at=absolute_expires_at or now + timedelta(days=2),
        last_activity_at=now - timedelta(minutes=5),
    )


def _user():
    return User(id=17, twitch_user_id="twitch-17", role="user", is_streamer=False)


def _request(*, method="GET", cookies=None, headers=None):
    return SimpleNamespace(
        method=method,
        cookies=cookies or {},
        headers=headers or {},
        state=SimpleNamespace(),
    )


@pytest.fixture(autouse=True)
def _auth_dependencies(monkeypatch):
    monkeypatch.setattr(deps, "get_backend_settings", lambda: SETTINGS)
    monkeypatch.setattr(deps, "apply_owner_bootstrap", lambda _user: False)

    async def _sync_ban(*_args, **_kwargs):
        return None

    async def _load_restrictions(_session, _user_id):
        return Restrictions()

    monkeypatch.setattr("services.twitch_ban_service.sync_user_twitch_ban", _sync_ban)
    monkeypatch.setattr(deps, "load_restrictions", _load_restrictions)


def _valid_request(method="GET", **extra_cookies):
    return _request(
        method=method,
        cookies={"backend_session_id": "session-token", **extra_cookies},
    )


async def test_missing_session_cookie_is_unauthorized():
    session = FakeSession()
    with pytest.raises(HTTPException) as exc_info:
        await deps._resolve_user(session, _request())
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail["code"] == "unauthorized"
    assert not session.committed


async def test_unknown_session_is_unauthorized():
    session = FakeSession(web_session=None)
    with pytest.raises(HTTPException) as exc_info:
        await deps._resolve_user(
            session,
            _request(cookies={"backend_session_id": "unknown"}),
        )
    assert exc_info.value.status_code == 401


@pytest.mark.parametrize(
    "expired",
    ["idle", "absolute"],
)
async def test_expired_session_is_deleted_and_rejected(expired):
    now = datetime.utcnow()
    row = _web_session(
        expires_at=now - timedelta(seconds=1)
        if expired == "idle"
        else now + timedelta(hours=1),
        absolute_expires_at=now - timedelta(seconds=1)
        if expired == "absolute"
        else now + timedelta(days=1),
    )
    session = FakeSession(web_session=row, user=_user())

    with pytest.raises(HTTPException) as exc_info:
        await deps._resolve_user(session, _valid_request())

    assert exc_info.value.status_code == 401
    assert session.deleted == [row]
    assert session.committed


async def test_missing_user_for_valid_session_is_unauthorized():
    session = FakeSession(web_session=_web_session(), user=None)
    with pytest.raises(HTTPException) as exc_info:
        await deps._resolve_user(session, _valid_request())
    assert exc_info.value.status_code == 401


@pytest.mark.parametrize(
    ("cookies", "headers", "csrf_hash"),
    [
        ({}, {}, "csrf"),
        ({"backend_csrf_token": "csrf"}, {}, "csrf"),
        ({}, {"X-CSRF-Token": "csrf"}, "csrf"),
        ({"backend_csrf_token": "other"}, {"X-CSRF-Token": "csrf"}, "csrf"),
        ({"backend_csrf_token": "csrf"}, {"X-CSRF-Token": "other"}, "csrf"),
        ({"backend_csrf_token": "csrf"}, {"X-CSRF-Token": "csrf"}, None),
        ({"backend_csrf_token": "csrf"}, {"X-CSRF-Token": "csrf"}, "other"),
    ],
)
async def test_write_request_rejects_invalid_csrf(cookies, headers, csrf_hash):
    row = _web_session(csrf=csrf_hash)
    session = FakeSession(web_session=row, user=_user())
    request = _request(
        method="PATCH",
        cookies={"backend_session_id": "session-token", **cookies},
        headers=headers,
    )

    with pytest.raises(HTTPException) as exc_info:
        await deps._resolve_user(session, request)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "csrf_failed"
    assert not session.committed


@pytest.mark.parametrize("method", ["GET", "HEAD", "OPTIONS"])
async def test_safe_methods_do_not_require_csrf(method):
    row = _web_session()
    session = FakeSession(web_session=row, user=_user())
    request = _valid_request(method=method)

    user = await deps._resolve_user(session, request)

    assert user.id == 17
    assert request.state.current_user is user
    assert request.state.actor.user_id == 17
    assert session.committed


async def test_valid_csrf_hashes_header_and_extends_idle_expiry():
    row = _web_session(csrf="known-csrf")
    user = _user()
    session = FakeSession(web_session=row, user=user)
    request = _request(
        method="POST",
        cookies={
            "backend_session_id": "session-token",
            "backend_csrf_token": "known-csrf",
        },
        headers={"X-CSRF-Token": "known-csrf"},
    )
    absolute_expiry = row.absolute_expires_at

    result = await deps._resolve_user(session, request)

    assert result is user
    assert row.last_activity_at > datetime.utcnow() - timedelta(seconds=5)
    assert row.expires_at > row.last_activity_at
    assert row.expires_at <= absolute_expiry
    assert session.committed


async def test_idle_expiry_is_capped_at_absolute_expiry():
    now = datetime.utcnow()
    row = _web_session(
        expires_at=now + timedelta(minutes=1),
        absolute_expires_at=now + timedelta(seconds=3),
    )
    session = FakeSession(web_session=row, user=_user())

    await deps._resolve_user(session, _valid_request())

    assert row.expires_at == row.absolute_expires_at


def test_require_capability_maps_service_ban():
    dependency = deps.require_capability(Capability.EDIT_TABLES)
    actor = Actor(
        user_id=1,
        role=Role.EDITOR,
        restrictions=Restrictions(service_banned=True),
    )

    with pytest.raises(HTTPException) as exc_info:
        dependency(actor)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "service_banned"


def test_require_recommend_maps_twitch_ban():
    dependency = deps.require_capability(Capability.RECOMMEND)
    actor = Actor(
        user_id=1,
        role=Role.USER,
        restrictions=Restrictions(twitch_banned=True),
    )

    with pytest.raises(HTTPException) as exc_info:
        dependency(actor)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "twitch_banned"


def test_require_admin_rejects_regular_user():
    actor = Actor(user_id=1, role=Role.USER)
    with pytest.raises(HTTPException) as exc_info:
        deps.require_admin(actor)
    assert exc_info.value.status_code == 403


def test_require_admin_accepts_owner():
    actor = Actor(user_id=1, role=Role.OWNER)
    assert deps.require_admin(actor) is actor


class _ApiSession(FakeSession):
    """Fake session for the real FastAPI dependency/route integration."""

    def __init__(self, web_session, user):
        super().__init__(web_session=web_session, user=user)

    async def get(self, model, user_id, **_kwargs):
        if model is User and user_id == self.user.id:
            return self.user
        # Let the protected route report not_found after authentication.
        return None


def test_write_endpoint_rejects_missing_csrf_header(monkeypatch):
    row = _web_session(csrf="known-csrf")
    user = _user()
    user.role = "editor"
    session = _ApiSession(row, user)

    async def _session_dep():
        yield session

    async def _no_ban(*_args, **_kwargs):
        return None

    async def _restrictions(_session, _user_id):
        return Restrictions()

    monkeypatch.setattr(deps, "apply_owner_bootstrap", lambda _user: False)
    monkeypatch.setattr(deps, "load_restrictions", _restrictions)
    monkeypatch.setattr("services.twitch_ban_service.sync_user_twitch_ban", _no_ban)
    app.dependency_overrides[deps.get_session] = _session_dep
    app.dependency_overrides[deps.get_streamer_id] = lambda: 17

    try:
        client = TestClient(app)
        client.cookies.set("backend_session_id", "session-token")
        client.cookies.set("backend_csrf_token", "known-csrf")
        response = client.patch(
            "/api/v1/games/999/streamer-state",
            json={"liked": True, "completed": False},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "csrf_failed"
    # CSRF fails before the request can reach the game mutation handler.
    assert not session.committed


def test_write_endpoint_accepts_matching_csrf_and_reaches_handler(monkeypatch):
    row = _web_session(csrf="known-csrf")
    user = _user()
    user.role = "editor"
    session = _ApiSession(row, user)

    async def _session_dep():
        yield session

    async def _no_ban(*_args, **_kwargs):
        return None

    async def _restrictions(_session, _user_id):
        return Restrictions()

    monkeypatch.setattr(deps, "apply_owner_bootstrap", lambda _user: False)
    monkeypatch.setattr(deps, "load_restrictions", _restrictions)
    monkeypatch.setattr("services.twitch_ban_service.sync_user_twitch_ban", _no_ban)
    app.dependency_overrides[deps.get_session] = _session_dep
    app.dependency_overrides[deps.get_streamer_id] = lambda: 17

    try:
        client = TestClient(app)
        client.cookies.set("backend_session_id", "session-token")
        client.cookies.set("backend_csrf_token", "known-csrf")
        response = client.patch(
            "/api/v1/games/999/streamer-state",
            headers={"X-CSRF-Token": "known-csrf"},
            json={"liked": True, "completed": False},
        )
    finally:
        app.dependency_overrides.clear()

    # Authentication and CSRF pass; the fake DB then reports no such game.
    assert response.status_code == 404
    assert response.json()["detail"]["code"] != "csrf_failed"
    assert session.committed
