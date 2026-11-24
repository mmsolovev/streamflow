"""Tests for exposing a live stream from runtime data."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.dialects import postgresql
from fastapi.testclient import TestClient

from backend.app import app
from backend.deps import get_session, get_streamer_id
from backend.repositories import games as games_repo
from backend.repositories import streams


class FakeResult:
    def __init__(self, *, row=None, rows=()):
        self.row = row
        self.rows = list(rows)

    def first(self):
        return self.row

    def all(self):
        return self.rows


class FakeSession:
    def __init__(self, *results):
        self.results = list(results)

    async def execute(self, statement):
        return self.results.pop(0)


def test_extract_twitch_mentions_deduplicates_case_insensitively():
    assert streams.extract_twitch_mentions(
        "Сегодня @WELOVEGAMES, потом @Tabula и снова @welovegames"
    ) == ["WELOVEGAMES", "Tabula"]


@pytest.mark.asyncio
async def test_current_stream_uses_fresh_samples_for_title_games_and_duration(monkeypatch):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    started_at = now - timedelta(minutes=95)
    runtime_session = SimpleNamespace(
        id=42,
        stream_id=7,
        started_at=started_at,
        last_sample_at=now,
        updated_at=now,
        created_at=started_at,
    )
    stream = SimpleNamespace(id=7, title="Заголовок при старте")
    samples = [
        (started_at, "Заголовок при старте @WELOVEGAMES", "Hades", "10"),
        (now, "Текущий заголовок @WELOVEGAMES", "Just Chatting", None),
        (now, "Текущий заголовок @WELOVEGAMES", "Hades", "10"),
    ]
    monkeypatch.setattr(streams.bot_settings, "TWITCH_PRIMARY_CHANNEL", "tabula")
    session = FakeSession(FakeResult(row=(runtime_session, stream)), FakeResult(rows=samples))

    current = await streams.get_current_stream(session)

    assert current is not None
    assert current["started_at"] == started_at
    assert current["title"] == "Текущий заголовок @WELOVEGAMES"
    assert current["games"] == ["Hades", "Just Chatting"]
    assert current["duration_minutes"] == 95
    assert current["channel_url"] == "https://www.twitch.tv/tabula"
    assert current["mentioned_logins"] == ["WELOVEGAMES"]


@pytest.mark.asyncio
async def test_stale_collecting_session_is_not_reported_as_live():
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    runtime_session = SimpleNamespace(
        id=42,
        stream_id=7,
        started_at=now - timedelta(hours=2),
        last_sample_at=now - timedelta(minutes=10),
        updated_at=now - timedelta(minutes=10),
        created_at=now - timedelta(hours=2),
    )
    session = FakeSession(
        FakeResult(row=(runtime_session, SimpleNamespace(id=7, title="Offline?")))
    )

    assert await streams.get_current_stream(session) is None


def test_historical_stream_filter_excludes_collecting_runtime_streams():
    condition = str(
        streams._not_collecting_stream().compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "NOT (EXISTS" in condition
    assert "stream_runtime_sessions.status" in condition
    assert "collecting" in condition


def test_runtime_game_durations_sum_repeated_categories():
    started = datetime(2026, 11, 20, 10, 0)
    samples = [
        (started + timedelta(seconds=10), "Hades", "10"),
        (started + timedelta(minutes=20), "Hollow Knight", "20"),
        (started + timedelta(minutes=40), "Hades", "10"),
    ]

    games = games_repo._runtime_game_durations(
        samples,
        started_at=started,
        ended_at=started + timedelta(minutes=60),
    )

    assert [(game["category_name"], game["duration_minutes"]) for game in games] == [
        ("Hades", 40),
        ("Hollow Knight", 20),
    ]


@pytest.mark.asyncio
async def test_live_game_islands_resolve_metadata_and_sum_session_time(monkeypatch):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    started_at = now - timedelta(minutes=35)
    runtime_session = SimpleNamespace(
        id=99,
        stream_id=7,
        status="collecting",
        started_at=started_at,
        ended_at=None,
        last_sample_at=now,
        updated_at=now,
        created_at=started_at,
    )
    stream = SimpleNamespace(id=7, ended_at=None)
    job = None
    monkeypatch.setattr(games_repo.bot_settings, "STREAM_RUNTIME_SAMPLE_SECONDS", 60)
    session = FakeSession(
        FakeResult(rows=[(runtime_session, stream, job)]),
        FakeResult(
            rows=[
                (
                    99,
                    started_at + timedelta(seconds=10),
                    "Hades",
                    None,
                )
            ]
        ),
        FakeResult(
            rows=[
                (
                    12,
                    "Hades",
                    None,
                    "https://store.steampowered.com/app/1145360",
                    "https://example.test/hades.jpg",
                )
            ]
        ),
    )

    islands = await games_repo.list_current_stream_games(session)

    assert islands == [
        {
            "key": "game:12",
            "stream_id": 7,
            "game_id": 12,
            "name": "Hades",
            "duration_minutes": 35,
            "steam_url": "https://store.steampowered.com/app/1145360",
            "cover_url": "https://example.test/hades.jpg",
            "is_live": True,
            "started_at": started_at,
            "first_played_at": started_at + timedelta(seconds=10),
            "ended_at": None,
        }
    ]


@pytest.mark.asyncio
async def test_finished_stream_games_remain_until_aggregation_is_done(monkeypatch):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    started_at = now - timedelta(minutes=50)
    ended_at = now - timedelta(minutes=10)
    runtime_session = SimpleNamespace(
        id=101,
        stream_id=8,
        status="finalized",
        started_at=started_at,
        ended_at=ended_at,
        last_sample_at=ended_at,
        updated_at=ended_at,
        created_at=started_at,
    )
    stream = SimpleNamespace(id=8, ended_at=ended_at)
    job = SimpleNamespace(status="pending")
    monkeypatch.setattr(games_repo.bot_settings, "STREAM_RUNTIME_SAMPLE_SECONDS", 60)
    session = FakeSession(
        FakeResult(rows=[(runtime_session, stream, job)]),
        FakeResult(
            rows=[
                (101, started_at, "Hades", None),
                (101, ended_at, "Hades", None),
            ]
        ),
        FakeResult(rows=[]),
    )

    islands = await games_repo.list_current_stream_games(session)

    assert len(islands) == 1
    assert islands[0]["is_live"] is False
    assert islands[0]["ended_at"] == ended_at
    assert islands[0]["duration_minutes"] == 40


@pytest.mark.asyncio
async def test_games_are_not_provisional_after_aggregation_is_done():
    assert await games_repo.list_current_stream_games(
        FakeSession(FakeResult(rows=[]))
    ) == []


def test_current_stream_endpoint_returns_live_snapshot():
    async def session_dep():
        yield object()

    app.dependency_overrides[get_session] = session_dep
    app.dependency_overrides[get_streamer_id] = lambda: 1
    live = {
        "id": 7,
        "started_at": "2026-11-20T12:00:00",
        "title": "Live stream",
        "games": ["Hades"],
        "duration_minutes": 45,
        "channel_url": "https://www.twitch.tv/tabula",
        "mentioned_logins": ["WELOVEGAMES"],
        "last_sample_at": "2026-11-20T12:45:00",
    }
    try:
        with patch(
            "backend.routers.streams.repo.get_current_stream",
            AsyncMock(return_value=live),
        ):
            response = TestClient(app).get("/api/v1/streams/current")
        assert response.status_code == 200
        assert response.json() == live
    finally:
        app.dependency_overrides.clear()


def test_current_stream_games_endpoint_returns_provisional_island():
    async def session_dep():
        yield object()

    app.dependency_overrides[get_session] = session_dep
    app.dependency_overrides[get_streamer_id] = lambda: 1
    island = {
        "key": "99:name:hades",
        "stream_id": 7,
        "game_id": 12,
        "name": "Hades",
        "duration_minutes": 35,
        "steam_url": "https://store.steampowered.com/app/1145360",
        "cover_url": None,
        "is_live": False,
        "started_at": "2026-11-20T12:00:00",
        "first_played_at": "2026-11-20T12:05:00",
        "ended_at": "2026-11-20T12:35:00",
        "game": None,
    }
    existing_game = {
        "id": 12,
        "name": "Hades",
        "rank": 4,
        "streams_count": 12,
        "hours": 100.0,
        "duration_minutes": 6000,
        "last_stream": "2026-11-19T12:00:00",
        "last_stream_id": 6,
        "hltb_all_styles": 20,
        "steam_url": "https://store.steampowered.com/app/1145360",
        "cover_url": None,
        "liked": True,
        "completed": False,
        "tags": "Action",
        "review_links": [],
    }
    try:
        with patch(
            "backend.routers.games.repo.list_current_stream_games",
            AsyncMock(return_value=[island]),
        ), patch(
            "backend.routers.games.repo.get_game_list_views",
            AsyncMock(return_value={12: existing_game}),
        ):
            response = TestClient(app).get("/api/v1/games/current-stream")
        assert response.status_code == 200
        assert response.json() == [{**island, "game": existing_game}]
    finally:
        app.dependency_overrides.clear()
