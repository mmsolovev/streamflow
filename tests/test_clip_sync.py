"""Bounded Twitch clip sync safety checks."""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from database import sync_clips
from services import clip_archive_sync_service


class FakeResponse:
    def __init__(self, status: int, payload: dict, headers: dict | None = None):
        self.status = status
        self.payload = payload
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def json(self):
        return self.payload


class FakeHTTP:
    def __init__(self, response: FakeResponse):
        self.response = response

    def get(self, *_args, **_kwargs):
        return self.response


def test_clip_api_errors_are_not_interpreted_as_empty_archive(monkeypatch):
    monkeypatch.setattr(sync_clips, "RATE_DELAY", 0)

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(sync_clips.asyncio, "sleep", no_sleep)
    with pytest.raises(sync_clips.TwitchClipAPIError, match="HTTP 503"):
        asyncio.run(
            sync_clips._api_get(
                FakeHTTP(FakeResponse(503, {"error": "unavailable"})),
                "https://api.twitch.tv/helix/clips",
                {},
                {},
                client_id="test-client",
            )
        )


def test_successful_empty_clip_response_is_a_valid_page(monkeypatch):
    monkeypatch.setattr(sync_clips, "RATE_DELAY", 0)

    result = asyncio.run(
        sync_clips._api_get(
            FakeHTTP(FakeResponse(200, {"data": [], "pagination": {}})),
            "https://api.twitch.tv/helix/clips",
            {},
            {},
            client_id="test-client",
        )
    )
    assert result["data"] == []


def test_clip_timestamps_are_normalized_to_naive_utc():
    assert sync_clips._parse_dt("2026-11-26T12:00:00+03:00") == datetime(
        2026, 11, 26, 9, 0
    )


class FakeJobSession:
    def __init__(self):
        self.added = []
        self.statement = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def execute(self, statement):
        self.statement = statement
        return SimpleNamespace(scalar_one_or_none=lambda: None)

    def add(self, job):
        self.added.append(job)

    async def commit(self):
        pass


def test_finalized_stream_refresh_is_persisted_for_twelve_minutes_later(monkeypatch):
    fake_session = FakeJobSession()
    monkeypatch.setattr(
        clip_archive_sync_service,
        "AsyncSessionLocal",
        lambda: fake_session,
    )
    ended_at = datetime(2026, 11, 26, 12, 0)
    worker = clip_archive_sync_service.ClipArchiveSyncWorker()

    asyncio.run(
        worker.on_stream_finalized(
            {
                "stream_id": "317408114772",
                "stream_db_id": 42,
                "ended_at": ended_at,
            }
        )
    )

    # The Twitch ID is a large external identifier; the job FK must use
    # the local streams.id from stream_db_id.
    assert fake_session.statement.whereclause.right.value == 42
    assert fake_session.added[0].stream_id == 42
    assert fake_session.added[0].check_at == ended_at + timedelta(minutes=12)


def test_finalized_stream_without_database_id_is_not_scheduled(monkeypatch):
    fake_session = FakeJobSession()
    monkeypatch.setattr(
        clip_archive_sync_service,
        "AsyncSessionLocal",
        lambda: fake_session,
    )
    worker = clip_archive_sync_service.ClipArchiveSyncWorker()

    asyncio.run(
        worker.on_stream_finalized(
            {
                "stream_id": "317408114772",
                "ended_at": datetime(2026, 11, 26, 12, 0),
            }
        )
    )

    assert fake_session.statement is None
    assert fake_session.added == []
