"""Регрессионные тесты жизненного цикла Telegram-анонсов."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from telegram import service as telegram_service_module
from telegram.service import TelegramService


class FakeSession:
    committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None

    async def commit(self):
        self.committed = True


@pytest.mark.asyncio
async def test_stream_resume_defers_previous_vod_check(monkeypatch):
    db = FakeSession()
    defer_jobs = AsyncMock(return_value=1)
    settings_row = SimpleNamespace(delay_seconds=660)
    monkeypatch.setattr(telegram_service_module, "AsyncSessionLocal", lambda: db)
    monkeypatch.setattr(
        telegram_service_module.post_edit_store,
        "get_settings",
        AsyncMock(return_value=settings_row),
    )
    monkeypatch.setattr(telegram_service_module.vod_jobs, "defer_recent_jobs", defer_jobs)

    service = TelegramService(enabled=True, token="token", channel_id=-100123)
    started_at = datetime(2026, 11, 11, 20, 5)
    await service.on_stream_started({"stream_id": "broadcast-new", "started_at": started_at})

    defer_jobs.assert_awaited_once_with(
        db,
        stream_id="broadcast-new",
        started_at=started_at,
        window_seconds=660,
    )
    assert db.committed


@pytest.mark.asyncio
async def test_stream_end_schedules_deferred_broadcasts_with_new_one(monkeypatch):
    db = FakeSession()
    create_job = AsyncMock(return_value=17)
    schedule_deferred = AsyncMock(return_value=1)
    monkeypatch.setattr(telegram_service_module, "AsyncSessionLocal", lambda: db)
    monkeypatch.setattr(
        telegram_service_module.post_edit_store,
        "get_settings",
        AsyncMock(return_value=SimpleNamespace(delay_seconds=660)),
    )
    monkeypatch.setattr(telegram_service_module.vod_jobs, "create_job", create_job)
    monkeypatch.setattr(
        telegram_service_module.vod_jobs,
        "schedule_deferred_jobs",
        schedule_deferred,
    )

    service = TelegramService(enabled=True, token="token", channel_id=-100123)
    service._bind_announcement = AsyncMock(return_value=42)
    started_at = datetime(2026, 11, 11, 20, 5)
    ended_at = datetime(2026, 11, 11, 21, 0)

    await service.on_stream_ended(
        {
            "stream_id": "broadcast-new",
            "stream_db_id": 3,
            "started_at": started_at,
            "ended_at": ended_at,
        }
    )

    create_job.assert_awaited_once_with(
        db,
        announcement_id=42,
        stream_id="broadcast-new",
        stream_db_id=3,
        stream_started_at=started_at,
        stream_ended_at=ended_at,
        check_delay_seconds=660,
    )
    schedule_deferred.assert_awaited_once_with(
        db,
        announcement_id=42,
        check_delay_seconds=660,
    )
    assert db.committed


@pytest.mark.asyncio
async def test_announcement_search_window_is_around_stream_start(monkeypatch):
    db = FakeSession()
    recent_posts = AsyncMock(return_value=[])
    monkeypatch.setattr(telegram_service_module.announcements, "recent_posts", recent_posts)
    monkeypatch.setattr(
        telegram_service_module.announcements,
        "recent_bound_ids",
        AsyncMock(return_value=set()),
    )

    service = TelegramService(enabled=True, token="token", channel_id=-100123)
    service.matcher = None
    service._find_rebind_candidate = AsyncMock(return_value=None)
    started_at = datetime(2026, 11, 11, 20, 0)
    await service._bind_announcement(
        db,
        stream_id="broadcast",
        started_at=started_at,
    )

    assert recent_posts.await_args.kwargs["posted_after"] == started_at - timedelta(hours=1)
    assert recent_posts.await_args.kwargs["posted_before"] == started_at + timedelta(hours=1)


@pytest.mark.asyncio
async def test_resumed_broadcast_reuses_announcement_with_deferred_job(monkeypatch):
    ended_at = datetime(2026, 11, 11, 20, 0)
    started_at = ended_at + timedelta(minutes=5)
    monkeypatch.setattr(
        telegram_service_module.vod_jobs,
        "recent_finished_streams",
        AsyncMock(return_value=[(42, ended_at)]),
    )
    monkeypatch.setattr(
        telegram_service_module.vod_jobs,
        "jobs_for_announcement",
        AsyncMock(return_value=[SimpleNamespace(stream_id="broadcast-old")]),
    )

    service = TelegramService(enabled=True, token="token", channel_id=-100123)
    announcement_id = await service._find_rebind_candidate(
        FakeSession(),
        stream_id="broadcast-new",
        started_at=started_at,
    )

    assert announcement_id == 42
