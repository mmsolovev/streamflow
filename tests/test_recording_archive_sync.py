"""Availability synchronization for Twitch archive records."""
import asyncio
from types import SimpleNamespace

import pytest

from pipeline.ingest.twitch_api import TwitchAPIResponseError, fetch_vods
from services.recording_service import mark_missing_unavailable


class FakeResult:
    def __init__(self, *, rows=()):
        self.rows = list(rows)

    def scalars(self):
        return self

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, results=()):
        self.results = list(results)
        self.deleted = []

    async def execute(self, _statement):
        return self.results.pop(0)

    async def delete(self, row):
        self.deleted.append(row)


class FakeResponse:
    def __init__(self, status, payload):
        self.status = status
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def json(self):
        return self.payload


class FakeHTTP:
    def __init__(self, response):
        self.response = response

    def get(self, *_args, **_kwargs):
        return self.response


def test_vod_sync_deletes_orphans_but_preserves_telegram_references():
    referenced = SimpleNamespace(
        id=1,
        stream_id=101,
        twitch_stream_id="broadcast-1",
        twitch_video_id="video-1",
        url="https://twitch.tv/videos/1",
        source="twitch",
        is_available=True,
        updated_at=None,
    )
    orphan = SimpleNamespace(
        id=2,
        stream_id=102,
        twitch_stream_id="broadcast-2",
        twitch_video_id="video-2",
        url="https://twitch.tv/videos/2",
        source="twitch",
        is_available=True,
        updated_at=None,
    )
    restored = SimpleNamespace(
        id=3,
        stream_id=103,
        twitch_stream_id="broadcast-3",
        twitch_video_id="video-3",
        url="https://twitch.tv/videos/3",
        source="twitch",
        is_available=False,
        updated_at=None,
    )
    telegram_ref = SimpleNamespace(
        recording_id=1,
        stream_db_id=None,
        stream_id="broadcast-1",
    )
    session = FakeSession(
        [
            FakeResult(rows=[referenced, orphan, restored]),
            FakeResult(rows=[telegram_ref]),
        ]
    )

    changed = asyncio.run(
        mark_missing_unavailable(
            session,
            keep_urls={"https://twitch.tv/videos/3"},
            keep_video_ids={"video-3"},
        )
    )

    assert changed == 3
    assert referenced.is_available is False
    assert orphan in session.deleted
    assert restored.is_available is True
    assert restored.updated_at is not None


@pytest.mark.asyncio
async def test_strict_archive_fetch_does_not_treat_api_error_as_empty_archive():
    with pytest.raises(TwitchAPIResponseError):
        await fetch_vods(
            FakeHTTP(FakeResponse(503, {"error": "unavailable"})),
            client_id="client",
            access_token="token",
            user_id="channel",
            strict_status=True,
        )


@pytest.mark.asyncio
async def test_successful_empty_archive_is_a_valid_empty_snapshot():
    vods = await fetch_vods(
        FakeHTTP(FakeResponse(200, {"data": [], "pagination": {}})),
        client_id="client",
        access_token="token",
        user_id="channel",
        strict_status=True,
    )

    assert vods == []
