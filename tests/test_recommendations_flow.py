"""High-value tests for recommendation business-flow decisions.

These tests exercise the full async orchestration in recommend_game while
isolating persistence and external lookups behind async fakes. They protect
against duplicate votes, recommendations for already streamed games, user
limits, IGDB adoption, and streamer-specific flags.
"""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import services.recommendations_service as recs
from services.recommendations_service import RecommendationSummary


class FakeSession:
    def __init__(self):
        self.committed = False
        self.added = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def commit(self):
        self.committed = True

    def add(self, obj):
        self.added.append(obj)


class SessionFactory:
    def __init__(self, session):
        self.session = session
        self.opens = 0

    def __call__(self):
        self.opens += 1
        return self.session


def _summary(title="Celeste"):
    return RecommendationSummary(
        id=7,
        title=title,
        status="released",
        release_date=None,
        steam_url=None,
        igdb_score=91.0,
        cover_url=None,
        recommenders=["Viewer"],
        votes_count=1,
    )


def _metadata(title="Celeste"):
    return SimpleNamespace(
        title=title,
        description_short="A platformer",
        release_date=datetime(2018, 9, 6),
        steam_url="https://store.steampowered.com/app/504230",
        rating_text="IGDB: 91.0",
        cover_url="https://images.example/celeste.jpg",
        source_game_id="12345",
        source_payload='{"id": 12345}',
    )


@pytest.fixture()
def flow(monkeypatch):
    session = FakeSession()
    factory = SessionFactory(session)
    monkeypatch.setattr(recs, "AsyncSessionLocal", factory)
    monkeypatch.setattr(recs, "GAMES_SHEET_URL", "https://sheet.example")
    monkeypatch.setattr(recs, "RECOMMENDATIONS_STREAMER_LOGIN", "tabula")

    async def not_banned(_login):
        return False

    monkeypatch.setattr(recs, "_user_is_banned", not_banned)
    monkeypatch.setattr(recs, "_find_streamed_game_match", AsyncMock(return_value=None))
    monkeypatch.setattr(recs, "build_game_response", AsyncMock(return_value="игра уже была"))
    monkeypatch.setattr(recs, "_db_find_game_by_query", AsyncMock(return_value=None))
    monkeypatch.setattr(recs, "_db_find_user_recommendation", AsyncMock(return_value=None))
    monkeypatch.setattr(recs, "_enforce_user_limit", AsyncMock(return_value=None))
    monkeypatch.setattr(recs, "_db_add_recommendation", AsyncMock())
    monkeypatch.setattr(recs, "build_recommendation_summary", AsyncMock(return_value=_summary()))
    monkeypatch.setattr(recs, "fetch_recommendation_metadata", AsyncMock(return_value=_metadata()))
    monkeypatch.setattr(recs, "fetch_igdb_metadata_by_id", AsyncMock(return_value=_metadata()))
    monkeypatch.setattr(recs, "_db_create_game_with_igdb", AsyncMock(return_value=SimpleNamespace(id=7, name="Celeste")))
    monkeypatch.setattr(recs, "_db_set_streamer_interested", AsyncMock())
    monkeypatch.setattr(recs, "_db_adopt_game_name", AsyncMock())

    return SimpleNamespace(session=session, factory=factory)


async def test_empty_query_is_rejected_before_ban_check(flow, monkeypatch):
    banned_check = AsyncMock(return_value=False)
    monkeypatch.setattr(recs, "_user_is_banned", banned_check)

    result = await recs.recommend_game(" !!! ", "viewer", "Viewer")

    assert result.outcome == "invalid"
    assert not result.accepted
    banned_check.assert_not_awaited()
    assert flow.factory.opens == 0


async def test_banned_user_gets_shadow_result_without_persisting(flow, monkeypatch):
    async def is_banned(_login):
        return True

    streamed_lookup = AsyncMock(return_value=None)
    monkeypatch.setattr(recs, "_user_is_banned", is_banned)
    monkeypatch.setattr(recs, "_find_streamed_game_match", streamed_lookup)

    result = await recs.recommend_game("Celeste", "banned", "Banned")

    assert result.outcome == "created"
    assert result.accepted
    assert flow.factory.opens == 0
    streamed_lookup.assert_not_awaited()


async def test_already_streamed_game_is_rejected_for_regular_user(flow, monkeypatch):
    monkeypatch.setattr(
        recs,
        "_find_streamed_game_match",
        AsyncMock(return_value=SimpleNamespace(name="Celeste")),
    )

    result = await recs.recommend_game("Celeste", "viewer", "Viewer")

    assert result.outcome == "already_streamed"
    assert not result.accepted
    recs.build_game_response.assert_awaited_once_with("Celeste")
    assert flow.factory.opens == 0


async def test_streamer_can_recommend_game_that_was_streamed(flow, monkeypatch):
    game = SimpleNamespace(id=7, name="Celeste")
    monkeypatch.setattr(
        recs,
        "_find_streamed_game_match",
        AsyncMock(return_value=game),
    )
    monkeypatch.setattr(recs, "_db_find_game_by_query", AsyncMock(return_value=game))

    result = await recs.recommend_game("Celeste", "tabula", "Tabula")

    assert result.outcome == "voted"
    assert result.accepted
    recs._db_add_recommendation.assert_awaited_once()
    assert flow.session.committed


async def test_existing_vote_is_not_duplicated(flow, monkeypatch):
    game = SimpleNamespace(id=7, name="Celeste")
    monkeypatch.setattr(recs, "_db_find_game_by_query", AsyncMock(return_value=game))
    monkeypatch.setattr(
        recs,
        "_db_find_user_recommendation",
        AsyncMock(return_value={"user_id": 3, "game_id": 7}),
    )

    result = await recs.recommend_game("Celeste", "viewer", "Viewer")

    assert result.outcome == "duplicate_vote"
    assert not result.accepted
    recs._db_add_recommendation.assert_not_awaited()
    assert not flow.session.committed


async def test_new_vote_for_existing_game_enforces_limit_and_commits(flow, monkeypatch):
    game = SimpleNamespace(id=7, name="Celeste")
    monkeypatch.setattr(recs, "_db_find_game_by_query", AsyncMock(return_value=game))
    monkeypatch.setattr(recs, "_enforce_user_limit", AsyncMock(return_value="Old Game"))
    monkeypatch.setattr(recs, "build_recommendation_summary", AsyncMock(return_value=_summary()))

    result = await recs.recommend_game(
        "Celeste", "viewer", "Viewer", note="looks fun"
    )

    assert result.outcome == "voted"
    assert result.accepted
    assert result.recommendation.title == "Celeste"
    assert "Old Game" in result.message
    recs._enforce_user_limit.assert_awaited_once_with(flow.session, "viewer")
    recs._db_add_recommendation.assert_awaited_once_with(
        flow.session, game, "viewer", note="looks fun"
    )
    assert flow.session.committed


async def test_missing_external_metadata_does_not_write(flow):
    recs.fetch_recommendation_metadata.return_value = None

    result = await recs.recommend_game("Unknown Game", "viewer", "Viewer")

    assert result.outcome == "not_found"
    assert not result.accepted
    recs._db_create_game_with_igdb.assert_not_awaited()
    recs._db_add_recommendation.assert_not_awaited()
    assert not flow.session.committed


async def test_metadata_title_matching_stream_is_rejected(flow, monkeypatch):
    calls = []

    async def streamed(query):
        calls.append(query)
        return None if query == "celeste?" else SimpleNamespace(name="Celeste")

    monkeypatch.setattr(recs, "_find_streamed_game_match", streamed)

    result = await recs.recommend_game("celeste?", "viewer", "Viewer")

    assert result.outcome == "already_streamed"
    assert calls == ["celeste?", "Celeste"]
    recs._db_create_game_with_igdb.assert_not_awaited()
    assert not flow.session.committed


async def test_new_game_is_created_and_recommendation_committed(flow):
    result = await recs.recommend_game(
        "Celeste", "viewer", "Viewer", note="must-play"
    )

    assert result.outcome == "created"
    assert result.accepted
    recs._db_create_game_with_igdb.assert_awaited_once()
    kwargs = recs._db_create_game_with_igdb.await_args.kwargs
    assert kwargs["name"] == "Celeste"
    assert kwargs["igdb_id"] == "12345"
    assert kwargs["igdb_score"] == 91.0
    recs._db_add_recommendation.assert_awaited_once_with(
        flow.session,
        SimpleNamespace(id=7, name="Celeste"),
        "viewer",
        note="must-play",
    )
    assert flow.session.committed


async def test_igdb_id_uses_authoritative_lookup(flow):
    result = await recs.recommend_game(
        "Celeste", "viewer", "Viewer", igdb_id="12345"
    )

    assert result.outcome == "created"
    recs.fetch_igdb_metadata_by_id.assert_awaited_once_with("12345")
    recs.fetch_recommendation_metadata.assert_not_awaited()


async def test_streamer_new_game_marks_interested(flow):
    result = await recs.recommend_game("Celeste", "tabula", "Tabula")

    assert result.outcome == "created"
    recs._db_set_streamer_interested.assert_awaited_once_with(
        flow.session, 7, "tabula", True
    )
    assert flow.session.committed


async def test_regular_user_new_game_does_not_mark_streamer_interested(flow):
    result = await recs.recommend_game("Celeste", "viewer", "Viewer")

    assert result.outcome == "created"
    recs._db_set_streamer_interested.assert_not_awaited()
