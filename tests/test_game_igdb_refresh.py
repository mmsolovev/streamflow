"""Tests for editor-triggered IGDB metadata refresh."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.deps import get_current_user, get_session
from backend.schemas.game import GameIGDBRefreshIn
from pipeline.ingest.igdb_api import RecommendationMetadata, _metadata_from_payload
from pipeline.load.load_game_meta import link_igdb_genres_and_platforms
from services import game_metadata_service


class FakeResult:
    def __init__(self, first=None, scalar=None):
        self._first = first
        self._scalar = scalar

    def first(self):
        return self._first

    def scalar_one_or_none(self):
        return self._scalar


class FakeSession:
    def __init__(self, game=None, results=()):
        self.game = game
        self.results = list(results)
        self.executed = []
        self.committed = False

    async def get(self, model, game_id):
        return self.game if self.game and self.game.id == game_id else None

    async def execute(self, statement):
        self.executed.append(statement)
        if self.results:
            return self.results.pop(0)
        return FakeResult()

    async def flush(self):
        pass

    async def commit(self):
        self.committed = True


def _metadata(igdb_id: str = "123") -> RecommendationMetadata:
    return RecommendationMetadata(
        title="Game from IGDB",
        description_short="A game",
        release_date=None,
        release_precision="unknown",
        steam_url="https://store.steampowered.com/app/123",
        rating_text="IGDB 90/100",
        platforms_text="PC",
        genres_text="Action",
        cover_url="https://example.test/cover.jpg",
        source_name="igdb",
        source_game_id=igdb_id,
        source_payload='{"summary": "A game", "genres": [], "platforms": []}',
    )


def test_igdb_payload_adapter_keeps_full_summary():
    summary = "Full game summary. " * 40
    metadata = _metadata_from_payload(
        {
            "id": 123,
            "name": "Game",
            "summary": summary,
        }
    )
    assert metadata.description_short == summary.strip()
    assert '"summary":' in metadata.source_payload


def test_refresh_patch_takes_full_summary_from_raw_payload():
    summary = "Full IGDB summary. " * 40
    metadata = _metadata()
    metadata.description_short = "Previously truncated summary…"
    metadata.source_payload = (
        '{"summary": '
        + json.dumps(summary)
        + ', "genres": [], "platforms": []}'
    )

    patch = game_metadata_service._metadata_patch(metadata)

    assert patch["description_en"] == summary.strip()


def test_refresh_body_requires_exactly_one_igdb_reference():
    assert GameIGDBRefreshIn(igdb_id="123").igdb_id == "123"
    assert GameIGDBRefreshIn(
        igdb_url="https://www.igdb.com/games/hades"
    ).igdb_url == "https://www.igdb.com/games/hades"
    with pytest.raises(ValueError):
        GameIGDBRefreshIn()
    with pytest.raises(ValueError):
        GameIGDBRefreshIn(igdb_id="123", igdb_url="https://www.igdb.com/games/hades")
    with pytest.raises(ValueError):
        GameIGDBRefreshIn(igdb_id="not-an-id")


@pytest.mark.asyncio
async def test_igdb_slug_link_resolves_by_exact_slug(monkeypatch):
    expected = _metadata()
    fetch_by_slug = AsyncMock(return_value=expected)
    monkeypatch.setattr(game_metadata_service, "fetch_igdb_metadata_by_slug", fetch_by_slug)

    result = await game_metadata_service._fetch_igdb_metadata_from_url(
        "https://www.igdb.com/games/hades"
    )

    assert result is expected
    fetch_by_slug.assert_awaited_once_with("hades")


@pytest.mark.asyncio
async def test_refresh_adds_metadata_and_links_without_removing_existing_taxonomy(
    monkeypatch,
):
    metadata = _metadata()
    metadata.description_short = "Truncated legacy value…"
    metadata.source_payload = (
        '{"summary": "Full summary from the IGDB raw payload.", '
        '"genres": [], "platforms": []}'
    )
    session = FakeSession(
        results=[FakeResult(scalar=None)],
    )
    apply_patch = AsyncMock(return_value=True)
    link_taxonomy = AsyncMock()
    monkeypatch.setattr(game_metadata_service, "fetch_igdb_metadata_by_id", AsyncMock(return_value=metadata))
    monkeypatch.setattr(game_metadata_service, "apply_igdb_patch", apply_patch)
    monkeypatch.setattr(
        game_metadata_service, "link_igdb_genres_and_platforms", link_taxonomy
    )

    await game_metadata_service.refresh_game_igdb(
        session,
        game_id=5,
        igdb_id="123",
    )

    patch = apply_patch.await_args.kwargs["patch"]
    assert patch["igdb_id"] == "123"
    assert patch["igdb_score"] == 90.0
    assert patch["description_en"] == "Full summary from the IGDB raw payload."
    link_taxonomy.assert_awaited_once()
    assert link_taxonomy.await_args.kwargs["payload"] == {
        "summary": "Full summary from the IGDB raw payload.",
        "genres": [],
        "platforms": [],
    }


@pytest.mark.asyncio
async def test_taxonomy_link_helper_never_deletes_existing_relations():
    # Both incoming targets already exist and are linked; the helper is
    # additive/idempotent and never issues DELETE for absent IGDB entries.
    session = FakeSession(
        results=[
            FakeResult(first=(1,)),  # genre id
            FakeResult(first=(5,)),  # existing game_genres link
            FakeResult(first=(2,)),  # platform id
            FakeResult(first=(5,)),  # existing game_platforms link
        ]
    )

    await link_igdb_genres_and_platforms(
        session,
        game_id=5,
        payload={
            "genres": [{"name": "Action"}],
            "platforms": [{"name": "PC"}],
        },
    )

    assert all(not getattr(statement, "is_delete", False) for statement in session.executed)


def test_refresh_endpoint_requires_editor_and_persists_result():
    async def session_dep():
        yield session

    game = SimpleNamespace(id=5)
    session = FakeSession(game=game)
    editor = SimpleNamespace(
        id=1,
        role="editor",
        is_streamer=False,
        current_profile=SimpleNamespace(login="editor", display_name="Editor"),
    )
    app.dependency_overrides[get_session] = session_dep
    app.dependency_overrides[get_current_user] = lambda: editor
    try:
        with patch(
            "services.game_metadata_service.refresh_game_igdb",
            AsyncMock(return_value=_metadata()),
        ):
            response = TestClient(app).post(
                "/api/v1/games/5/refresh-igdb",
                json={"igdb_id": "123"},
            )
        assert response.status_code == 200
        assert response.json()["igdb_id"] == "123"
        assert session.committed

        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=2,
            role="user",
            is_streamer=False,
            current_profile=SimpleNamespace(login="viewer", display_name="Viewer"),
        )
        denied = TestClient(app).post(
            "/api/v1/games/5/refresh-igdb",
            json={"igdb_id": "123"},
        )
        assert denied.status_code == 403
    finally:
        app.dependency_overrides.clear()
