"""Privilege-boundary and audit tests for administrative operations.

The tests call the router handlers directly with fake persistence. They focus
on owner protection, role escalation, service-ban lifecycle, session revocation,
and audit records rather than schema/formatting details.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

import backend.routers.admin as admin
from backend.schemas.admin import RoleChangeBody, ServiceBanBody
from database.models import (
    ModerationAudit,
    User,
    UserProfile,
    UserRestriction,
    WebSession,
)
from services.authz_service import Actor, Role


class FakeResult:
    def __init__(self, scalar=None, rows=None):
        self._scalar = scalar
        self._rows = list(rows or [])

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return self

    def all(self):
        return self._rows


class FakeSession:
    def __init__(self, *, target=None, get_rows=None, results=None):
        self.target = target
        self.get_rows = dict(get_rows or {})
        self.results = list(results or [])
        self.executed = []
        self.added = []
        self.committed = False
        self.flushed = False

    async def get(self, model, pk):
        if model is User:
            return self.target
        return self.get_rows.get((model, pk))

    async def execute(self, statement):
        self.executed.append(statement)
        if self.results:
            return self.results.pop(0)
        return FakeResult()

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushed = True
        for obj in self.added:
            if isinstance(obj, UserRestriction) and obj.id is None:
                obj.id = 901

    async def commit(self):
        self.committed = True


def _request():
    return SimpleNamespace(
        client=SimpleNamespace(host="192.0.2.10"),
        headers={"user-agent": "pytest-security"},
    )


def _actor(role=Role.OWNER):
    return Actor(user_id=1, role=role)


def _target(role="user", user_id=2):
    return User(
        id=user_id,
        twitch_user_id=f"twitch-{user_id}",
        role=role,
        is_streamer=False,
        created_at=datetime(2026, 1, 1),
    )


@pytest.fixture(autouse=True)
def _no_cache(monkeypatch):
    calls = []
    monkeypatch.setattr(admin, "invalidate_actor_cache", lambda: calls.append(True))
    return calls


async def test_owner_cannot_be_demoted():
    session = FakeSession(target=_target("owner"))
    with pytest.raises(HTTPException) as exc_info:
        await admin.change_role(
            2,
            RoleChangeBody(role="user"),
            _request(),
            session,
            _actor(),
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "owner_protected"
    assert not session.committed
    assert not session.added


@pytest.mark.parametrize("requested_role", ["admin", "streamer"])
async def test_non_owner_cannot_escalate_user_role(requested_role):
    session = FakeSession(target=_target("user"))

    with pytest.raises(HTTPException) as exc_info:
        await admin.change_role(
            2,
            RoleChangeBody(role=requested_role),
            _request(),
            session,
            _actor(Role.ADMIN),
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "forbidden"
    assert not session.committed


def test_owner_role_cannot_be_assigned_through_role_body():
    # Owner is bootstrap-protected and is intentionally not a requestable role.
    with pytest.raises(ValidationError):
        RoleChangeBody(role="owner")


async def test_non_owner_cannot_change_admin_role():
    session = FakeSession(target=_target("admin"))

    with pytest.raises(HTTPException) as exc_info:
        await admin.change_role(
            2,
            RoleChangeBody(role="user"),
            _request(),
            session,
            _actor(Role.STREAMER),
        )

    assert exc_info.value.status_code == 403
    assert not session.committed


async def test_admin_can_promote_regular_user_to_editor():
    target = _target("user")
    session = FakeSession(
        target=target,
        results=[
            FakeResult(),  # DELETE web_sessions
            FakeResult(scalar=UserProfile(user_id=2, is_current=True, login="viewer")),
            FakeResult(rows=[]),
        ],
    )

    view = await admin.change_role(
        2,
        RoleChangeBody(role="editor", reason="trusted contributor"),
        _request(),
        session,
        _actor(Role.ADMIN),
    )

    assert target.role == "editor"
    assert view.role == "editor"
    assert session.committed
    audit = next(obj for obj in session.added if isinstance(obj, ModerationAudit))
    assert audit.action == "role_changed"
    assert audit.old_value == "user"
    assert audit.new_value == "editor"
    assert audit.reason == "trusted contributor"


async def test_owner_role_change_revokes_sessions_and_writes_audit(_no_cache):
    target = _target("editor")
    session = FakeSession(
        target=target,
        results=[
            FakeResult(),  # DELETE web_sessions
            FakeResult(scalar=UserProfile(user_id=2, is_current=True, login="viewer")),
            FakeResult(rows=[]),
        ],
    )

    view = await admin.change_role(
        2,
        RoleChangeBody(role="user", reason="access review"),
        _request(),
        session,
        _actor(Role.OWNER),
    )

    assert target.role == "user"
    assert view.role == "user"
    assert session.committed
    assert len(session.executed) == 3
    revoke_sql = str(session.executed[0]).lower()
    assert "web_sessions" in revoke_sql and "delete" in revoke_sql
    audits = [obj for obj in session.added if isinstance(obj, ModerationAudit)]
    assert len(audits) == 1
    audit = audits[0]
    assert audit.actor_user_id == 1
    assert audit.target_user_id == 2
    assert audit.action == "role_changed"
    assert audit.old_value == "editor"
    assert audit.new_value == "user"
    assert audit.reason == "access review"
    assert audit.ip == "192.0.2.10"
    assert audit.user_agent == "pytest-security"
    assert _no_cache == [True]


async def test_service_ban_protects_owner():
    session = FakeSession(target=_target("owner"))
    with pytest.raises(HTTPException) as exc_info:
        await admin.create_service_ban(
            2,
            ServiceBanBody(reason="abuse"),
            _request(),
            session,
            _actor(),
        )

    assert exc_info.value.detail["code"] == "owner_protected"
    assert not session.committed


async def test_service_ban_rejects_duplicate_active_ban():
    active = UserRestriction(
        user_id=2,
        kind="service_ban",
        reason="existing",
        source="manual",
        created_at=datetime.utcnow(),
    )
    session = FakeSession(target=_target(), results=[FakeResult(scalar=active)])

    with pytest.raises(HTTPException) as exc_info:
        await admin.create_service_ban(
            2,
            ServiceBanBody(reason="again"),
            _request(),
            session,
            _actor(),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "already_banned"
    assert not session.committed


async def test_service_ban_persists_restriction_revokes_sessions_and_audits(_no_cache):
    session = FakeSession(target=_target(), results=[FakeResult(), FakeResult()])
    expires = datetime(2027, 1, 1, tzinfo=timezone(timedelta(hours=3)))

    restriction = await admin.create_service_ban(
        2,
        ServiceBanBody(reason="spam", expires_at=expires),
        _request(),
        session,
        _actor(),
    )

    row = next(obj for obj in session.added if isinstance(obj, UserRestriction))
    audit = next(obj for obj in session.added if isinstance(obj, ModerationAudit))
    assert restriction.kind == "service_ban"
    assert restriction.reason == "spam"
    assert row.expires_at == datetime(2026, 12, 31, 21, 0)
    assert session.flushed
    assert row.id == 901
    assert session.committed
    assert "delete" in str(session.executed[1]).lower()
    assert "web_sessions" in str(session.executed[1]).lower()
    assert audit.action == "service_ban_created"
    assert audit.target_user_id == 2
    assert audit.new_value == "901"
    assert audit.reason == "spam"
    assert _no_cache == [True]


@pytest.mark.parametrize(
    "row",
    [
        None,
        UserRestriction(
            id=4,
            user_id=3,
            kind="service_ban",
            reason="wrong user",
            source="manual",
        ),
        UserRestriction(
            id=4,
            user_id=2,
            kind="twitch_ban",
            reason="wrong kind",
            source="twitch",
        ),
    ],
)
async def test_lift_service_ban_rejects_missing_or_foreign_restriction(row):
    session = FakeSession(get_rows={(UserRestriction, 4): row})

    with pytest.raises(HTTPException) as exc_info:
        await admin.lift_service_ban(2, 4, _request(), session, _actor())

    assert exc_info.value.status_code == 404
    assert not session.committed


async def test_lifting_ban_is_idempotent():
    row = UserRestriction(
        id=4,
        user_id=2,
        kind="service_ban",
        reason="done",
        source="manual",
        lifted_at=datetime(2026, 1, 1),
    )
    session = FakeSession(get_rows={(UserRestriction, 4): row})

    result = await admin.lift_service_ban(2, 4, _request(), session, _actor())

    assert result is None
    assert not session.committed


async def test_lift_service_ban_audits_and_commits(_no_cache):
    row = UserRestriction(
        id=4,
        user_id=2,
        kind="service_ban",
        reason="spam",
        source="manual",
        lifted_at=None,
    )
    session = FakeSession(get_rows={(UserRestriction, 4): row})

    result = await admin.lift_service_ban(2, 4, _request(), session, _actor())

    assert result is None
    assert row.lifted_at is not None
    assert session.committed
    audit = next(obj for obj in session.added if isinstance(obj, ModerationAudit))
    assert audit.action == "service_ban_lifted"
    assert audit.old_value == "4"
    assert audit.reason == "spam"
    assert _no_cache == [True]


async def test_change_role_not_found_has_stable_error():
    session = FakeSession(target=None)

    with pytest.raises(HTTPException) as exc_info:
        await admin.change_role(
            999,
            RoleChangeBody(role="editor"),
            _request(),
            session,
            _actor(),
        )

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail["code"] == "not_found"
