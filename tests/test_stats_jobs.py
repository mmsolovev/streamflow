"""Очередь отложенной агрегации `game_stats`.

Проверяется чистый слой `runtime.aggregation_jobs`: backoff ретраев, переходы
статусов и время `check_at` (стрим + 11 минут). База не нужна — сессия
подменяется минимальным fake-объектом.

Запуск:
    .venv\\Scripts\\python.exe -m pytest tests/test_stats_jobs.py -q
"""

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


def _delay(attempts: int) -> float:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return (next_retry_at(attempts) - now).total_seconds()


def test_first_attempt_waits_base_delay():
    assert abs(_delay(1) - RETRY_BASE_SECONDS) <= 2


def test_backoff_grows_and_is_capped():
    assert abs(_delay(3) - RETRY_BASE_SECONDS * 4) <= 2
    assert abs(_delay(20) - RETRY_MAX_SECONDS) <= 2


def _job(attempts: int) -> SimpleNamespace:
    return SimpleNamespace(
        attempts=attempts,
        status="processing",
        last_error=None,
        locked_at=datetime(2026, 1, 1),
        locked_by="worker",
        check_at=datetime(2026, 1, 1),
        updated_at=None,
    )


async def test_below_limit_returns_job_to_queue():
    job = _job(attempts=2)

    await mark_failed(FakeSession(), job, "boom")

    assert job.status == "pending"
    assert job.last_error == "boom"
    assert job.locked_at is None
    assert job.locked_by is None
    assert job.check_at > datetime(2026, 1, 1)


async def test_limit_marks_job_as_failed():
    job = _job(attempts=MAX_ATTEMPTS)

    await mark_failed(FakeSession(), job, "boom")

    assert job.status == "failed"
    assert job.locked_at is None


async def test_long_error_is_truncated():
    job = _job(attempts=1)

    await mark_failed(FakeSession(), job, "x" * 5000)

    assert len(job.last_error) == 2000


async def test_check_at_is_ended_at_plus_delay():
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

    assert isinstance(job, StreamStatsJob)
    assert job.check_at == ended_at + timedelta(seconds=660)
    assert job.status == "pending"
    assert job.attempts == 0
    assert job.stream_id == 20
    assert job.stream_session_id == 10
    assert db.added == [job]
