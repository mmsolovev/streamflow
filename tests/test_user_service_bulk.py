"""Регрессии `get_or_create_users_bulk`.

Ошибка со стрима: два сообщения одного зрителя в одном батче. Первое создавало
`User` без `id` (flush ещё не было), второе находило его и падало на
`int(user.id)` — `TypeError`. Тест не трогает PostgreSQL: сессия подменена.
"""

from database.models import User, UserProfile
from services.user_service import get_or_create_users_bulk


class _FakeResult:
    def __init__(self, rows=None):
        self._rows = list(rows or [])

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    """Пустая БД + выдача id на flush, как у настоящей сессии."""

    def __init__(self):
        self.added = []
        self._next_id = 1
        self.flushes = 0

    async def execute(self, _statement):
        return _FakeResult()

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        self.flushes += 1
        for obj in self.added:
            if isinstance(obj, User) and obj.id is None:
                obj.id = self._next_id
                self._next_id += 1


async def test_same_new_user_with_two_keys_does_not_crash():
    session = _FakeSession()

    result = await get_or_create_users_bulk(
        session,
        [
            ("123", "viewer", "Viewer"),
            (None, "viewer", "Viewer"),
        ],
    )

    assert "123" in result
    assert "viewer" in result
    assert result["123"] is result["viewer"]
    profiles = [obj for obj in session.added if isinstance(obj, UserProfile)]
    assert len(profiles) == 1
    assert profiles[0].user_id == result["123"].id


async def test_duplicate_identity_is_processed_once():
    session = _FakeSession()

    result = await get_or_create_users_bulk(
        session,
        [
            ("123", "viewer", "Viewer"),
            ("123", "viewer", "Viewer"),
        ],
    )

    assert list(result) == ["123"]
    users = [obj for obj in session.added if isinstance(obj, User)]
    profiles = [obj for obj in session.added if isinstance(obj, UserProfile)]
    assert len(users) == 1
    assert len(profiles) == 1


async def test_different_new_users_get_separate_profiles():
    session = _FakeSession()

    result = await get_or_create_users_bulk(
        session,
        [
            ("1", "one", "One"),
            ("2", "two", "Two"),
        ],
    )

    assert len(result) == 2
    assert result["1"] is not result["2"]
    profiles = [obj for obj in session.added if isinstance(obj, UserProfile)]
    assert {profile.login for profile in profiles} == {"one", "two"}
