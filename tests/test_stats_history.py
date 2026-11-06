"""История изменений статистики: сериализация и батчи.

Проверяется `services.stats_history` без PostgreSQL: fake-сессия только
назначает id батчам и складывает объекты. Важно, чтобы пустые изменения не
создавали батч, а значения полей корректно переживали запись в текст и обратно.

Запуск:
    .venv\\Scripts\\python.exe -m unittest tests.test_stats_history -v
"""

import unittest
from datetime import datetime
from types import SimpleNamespace

from database.models import StatsChangeBatch, StatsChangeLog
from services import stats_history


class FakeSession:
    def __init__(self):
        self.added = []
        self._next_id = 1

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = self._next_id
                self._next_id += 1


class SerializeValueTests(unittest.TestCase):
    def test_none_stays_none(self):
        self.assertIsNone(stats_history.serialize_value(None))

    def test_datetime_is_normalized_to_naive_utc(self):
        value = datetime.fromisoformat("2026-01-01T03:00:00+03:00")

        self.assertEqual(stats_history.serialize_value(value), "2026-01-01T00:00:00")

    def test_numbers_and_bool_are_text(self):
        self.assertEqual(stats_history.serialize_value(12), "12")
        self.assertEqual(stats_history.serialize_value(1.5), "1.5")
        self.assertEqual(stats_history.serialize_value(True), "1")
        self.assertEqual(stats_history.serialize_value(False), "0")


class ParseValueTests(unittest.TestCase):
    def test_none_stays_none(self):
        self.assertIsNone(stats_history.parse_value(None, int))

    def test_datetime(self):
        self.assertEqual(
            stats_history.parse_value("2026-01-01T00:00:00", datetime),
            datetime(2026, 1, 1),
        )
        self.assertIsNone(stats_history.parse_value("bad", datetime))

    def test_int_accepts_float_text(self):
        self.assertEqual(stats_history.parse_value("12", int), 12)
        self.assertEqual(stats_history.parse_value("12.9", int), 12)
        self.assertIsNone(stats_history.parse_value("bad", int))

    def test_float(self):
        self.assertEqual(stats_history.parse_value("1.5", float), 1.5)
        self.assertIsNone(stats_history.parse_value("bad", float))

    def test_bool(self):
        self.assertFalse(stats_history.parse_value("0", bool))
        self.assertFalse(stats_history.parse_value("false", bool))
        self.assertTrue(stats_history.parse_value("1", bool))
        self.assertTrue(stats_history.parse_value("true", bool))

    def test_unknown_type_returns_text(self):
        self.assertEqual(stats_history.parse_value("abc", str), "abc")
        self.assertEqual(stats_history.parse_value("abc", None), "abc")


class DiffValuesTests(unittest.TestCase):
    def test_returns_only_changed_fields(self):
        target = SimpleNamespace(title="Old", duration_minutes=10, ended_at=None)

        changes = stats_history.diff_values(
            target,
            {"title": "Old", "duration_minutes": 12, "ended_at": None},
        )

        self.assertEqual(changes, [("duration_minutes", 10, 12)])

    def test_datetime_comparison_ignores_timezone_representation(self):
        target = SimpleNamespace(
            started_at=datetime.fromisoformat("2026-01-01T00:00:00+00:00")
        )

        changes = stats_history.diff_values(
            target,
            {"started_at": datetime.fromisoformat("2026-01-01T00:00:00")},
        )

        self.assertEqual(changes, [])


class ApplyChangesTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_changes_do_not_create_batch(self):
        session = FakeSession()

        batch = await stats_history.apply_changes(
            session,
            [],
            source=stats_history.SOURCE_RUNTIME,
        )

        self.assertIsNone(batch)
        self.assertEqual(session.added, [])

    async def test_equal_values_do_not_create_batch(self):
        session = FakeSession()

        batch = await stats_history.apply_changes(
            session,
            [
                (
                    stats_history.ENTITY_GAME_STATS,
                    1,
                    "duration_minutes",
                    10,
                    10,
                )
            ],
            source=stats_history.SOURCE_RUNTIME,
        )

        self.assertIsNone(batch)
        self.assertEqual(session.added, [])

    async def test_changes_are_grouped_into_one_batch(self):
        session = FakeSession()

        batch = await stats_history.apply_changes(
            session,
            [
                (
                    stats_history.ENTITY_GAME_STATS,
                    1,
                    "duration_minutes",
                    10,
                    12,
                ),
                (
                    stats_history.ENTITY_GAME_STATS,
                    2,
                    "duration_minutes",
                    None,
                    30,
                ),
            ],
            source=stats_history.SOURCE_RUNTIME,
            reason="test",
            stream_id=7,
        )

        self.assertIsInstance(batch, StatsChangeBatch)
        self.assertEqual(batch.status, stats_history.STATUS_APPLIED)
        self.assertEqual(batch.changes_count, 2)
        self.assertEqual(batch.source, stats_history.SOURCE_RUNTIME)
        self.assertEqual(batch.reason, "test")
        self.assertEqual(batch.stream_id, 7)

        logs = [row for row in session.added if isinstance(row, StatsChangeLog)]
        self.assertEqual(len(logs), 2)
        self.assertEqual(logs[0].old_value, "10")
        self.assertEqual(logs[0].new_value, "12")
        self.assertEqual(logs[1].old_value, None)
        self.assertEqual(logs[1].new_value, "30")


if __name__ == "__main__":
    unittest.main()
