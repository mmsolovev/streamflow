"""Очередь отложенной агрегации `game_stats`.

Проверяется чистый слой `runtime.aggregation_jobs`: backoff ретраев, переходы
статусов и время `check_at` (стрим + 11 минут). База не нужна — сессия
подменяется минимальным fake-объектом.

Запуск:
    .venv\\Scripts\\python.exe -m unittest tests.test_stats_jobs -v
"""

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from database.models import StreamStatsJob
from runtime.aggregation_jobs import (
    MAX_ATTEMPTS,
    RETRY_BASE_SECONDS,
    RETRY_MAX_SECONDS,
    mark_failed,
    next_retry_at,
)
from runtime.repository import enqueue_stats_job


class FakeResult:
    def scalar_one_or_none(self):
        return None


class FakeSession:
    def __init__(self):
        self.added = []

    async def execute(self, *_args, **_kwargs):
        return FakeResult()

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass


class NextRetryAtTests(unittest.TestCase):
    @staticmethod
    def _delay(attempts: int) -> float:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        return (next_retry_at(attempts) - now).total_seconds()

    def test_first_attempt_waits_base_delay(self):
        self.assertAlmostEqual(self._delay(1), RETRY_BASE_SECONDS, delta=2)

    def test_backoff_grows_and_is_capped(self):
        self.assertAlmostEqual(self._delay(3), RETRY_BASE_SECONDS * 4, delta=2)
        self.assertAlmostEqual(self._delay(20), RETRY_MAX_SECONDS, delta=2)


class MarkFailedTests(unittest.IsolatedAsyncioTestCase):
    def _job(self, attempts: int) -> SimpleNamespace:
        return SimpleNamespace(
            attempts=attempts,
            status="processing",
            last_error=None,
            locked_at=datetime(2026, 1, 1),
            locked_by="worker",
            check_at=datetime(2026, 1, 1),
            updated_at=None,
        )

    async def test_below_limit_returns_job_to_queue(self):
        job = self._job(attempts=2)

        await mark_failed(FakeSession(), job, "boom")

        self.assertEqual(job.status, "pending")
        self.assertEqual(job.last_error, "boom")
        self.assertIsNone(job.locked_at)
        self.assertIsNone(job.locked_by)
        self.assertGreater(job.check_at, datetime(2026, 1, 1))

    async def test_limit_marks_job_as_failed(self):
        job = self._job(attempts=MAX_ATTEMPTS)

        await mark_failed(FakeSession(), job, "boom")

        self.assertEqual(job.status, "failed")
        self.assertIsNone(job.locked_at)

    async def test_long_error_is_truncated(self):
        job = self._job(attempts=1)

        await mark_failed(FakeSession(), job, "x" * 5000)

        self.assertEqual(len(job.last_error), 2000)


class EnqueueStatsJobTests(unittest.IsolatedAsyncioTestCase):
    async def test_check_at_is_ended_at_plus_delay(self):
        ended_at = datetime(2026, 1, 1, 12, 0)
        session = SimpleNamespace(
            id=10,
            stream_id=20,
            ended_at=ended_at,
        )
        db = FakeSession()

        with patch(
            "runtime.repository.settings.STREAM_STATS_AGGREGATION_DELAY_SECONDS",
            660,
        ):
            job = await enqueue_stats_job(db, session)

        self.assertIsInstance(job, StreamStatsJob)
        self.assertEqual(job.check_at, ended_at + timedelta(seconds=660))
        self.assertEqual(job.status, "pending")
        self.assertEqual(job.attempts, 0)
        self.assertEqual(job.stream_id, 20)
        self.assertEqual(job.stream_session_id, 10)
        self.assertEqual(db.added, [job])


if __name__ == "__main__":
    unittest.main()
