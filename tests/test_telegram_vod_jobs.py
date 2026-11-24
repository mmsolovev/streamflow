"""Тесты vod_jobs: backoff, rebind и отложенные VOD-задачи.

Проверяется чистая логика времени — она решает, когда задача будет
обработана снова, и поэтому обязана быть детерминированной.

Запуск:
    .venv\\Scripts\\python.exe -m pytest tests/test_telegram_vod_jobs.py -q
"""
import asyncio
from datetime import datetime, timedelta, timezone

from telegram.vod_jobs import RETRY_BASE_SECONDS, RETRY_MAX_SECONDS, next_retry_at
from telegram.vod_jobs import defer_recent_jobs, mark_no_vod, schedule_deferred_jobs
from telegram.matcher import in_rebind_window


def _delay(attempts: int) -> float:
    # next_retry_at отдаёт naive UTC, поэтому и «сейчас» берём в UTC:
    # сравнение с локальным временем дало бы сдвиг в часовых пояса.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return (next_retry_at(attempts) - now).total_seconds()


def test_first_attempt_uses_base_delay():
    # Считаем с attempts=1: первая неудача ждёт столько же, сколько база.
    assert abs(_delay(1) - RETRY_BASE_SECONDS) <= 5


def test_delay_grows():
    assert _delay(2) > _delay(1)
    assert _delay(3) > _delay(2)


def test_delay_capped():
    assert _delay(50) <= RETRY_MAX_SECONDS + 5


def test_zero_attempts_does_not_shift_back():
    assert abs(_delay(0) - RETRY_BASE_SECONDS) <= 5


def test_future_check_time():
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    assert next_retry_at(1) > now


NEW_START = datetime(2026, 10, 1, 21, 5)


def test_restart_within_window():
    """Краш трансляции: новый broadcast продолжает старый анонс."""
    previous_end = NEW_START - timedelta(minutes=10)
    assert in_rebind_window(previous_end, NEW_START, window_minutes=180)


def test_restart_at_window_edge():
    previous_end = NEW_START - timedelta(minutes=180)
    assert in_rebind_window(previous_end, NEW_START, window_minutes=180)


def test_restart_outside_window():
    # Стрим завершился 5 часов назад — это другой анонс, а не продолжение.
    previous_end = NEW_START - timedelta(hours=5)
    assert not in_rebind_window(previous_end, NEW_START, window_minutes=180)


def test_typical_crash_pattern():
    # Стрим упал в 21:00, перезапуск в 21:05 — обычный случай.
    assert in_rebind_window(
        datetime(2026, 10, 1, 21, 0), datetime(2026, 10, 1, 21, 5), 180
    )


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows


class _FakeSession:
    def __init__(self, rows):
        self.rows = rows

    async def execute(self, _statement):
        return _Rows(self.rows)


class _StatementSession:
    def __init__(self):
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return None


def test_resume_removes_waiting_job_from_due_queue():
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    job = type("Job", (), {"check_at": now, "updated_at": None})()
    session = _FakeSession([job])

    changed = asyncio.run(
        defer_recent_jobs(
            session,
            stream_id="new-broadcast",
            started_at=now,
            window_seconds=660,
        )
    )

    assert changed == 1
    assert job.check_at is None
    assert job.updated_at is not None


def test_final_offline_reschedules_deferred_jobs():
    job = type("Job", (), {"check_at": None, "updated_at": None})()
    session = _FakeSession([job])

    changed = asyncio.run(
        schedule_deferred_jobs(session, announcement_id=42, check_delay_seconds=660)
    )

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    assert changed == 1
    assert now + timedelta(seconds=655) <= job.check_at <= now + timedelta(seconds=665)
    assert job.updated_at is not None


def test_missing_vod_is_retried_with_backoff():
    session = _StatementSession()
    exhausted = asyncio.run(
        mark_no_vod(
            session,
            job_id=7,
            reason="not published yet",
            attempts=1,
            max_attempts=5,
        )
    )

    params = session.statement.compile().params
    assert not exhausted
    assert params["status"] == "waiting"
    assert params["attempts"] == 1
    assert params["check_at"] > datetime.now(timezone.utc).replace(tzinfo=None)


def test_missing_vod_is_terminal_after_max_attempts():
    session = _StatementSession()
    exhausted = asyncio.run(
        mark_no_vod(
            session,
            job_id=7,
            reason="not published",
            attempts=5,
            max_attempts=5,
        )
    )

    params = session.statement.compile().params
    assert exhausted
    assert params["status"] == "no_vod"
    assert params["check_at"] is None
