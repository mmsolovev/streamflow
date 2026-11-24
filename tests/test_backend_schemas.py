"""Tests for web schemas (Pydantic DTOs)."""
import pytest

from backend.schemas.bot_command import BotCommandCreateIn, BotCommandStateUpdateIn
from backend.schemas.common import Page
from backend.schemas.game import GameStateUpdateIn, GameView
from backend.schemas.recommendation import RecommendationView
from backend.schemas.release import ReleaseView


def test_page_serializes_generic_items():
    page = Page[GameView](items=[], total=0, limit=10, offset=0)
    assert page.model_dump() == {
        "items": [],
        "total": 0,
        "limit": 10,
        "offset": 0,
        "total_all": None,
        "aggregates": None,
    }


def test_page_carries_totals_and_aggregates():
    page = Page[GameView](
        items=[],
        total=5,
        limit=10,
        offset=0,
        total_all=42,
        aggregates={"liked": 3},
    )
    body = page.model_dump()
    assert body["total"] == 5
    assert body["total_all"] == 42
    assert body["aggregates"] == {"liked": 3}


def test_game_view_from_dict():
    view = GameView(
        id=1,
        name="Hades",
        rank=2,
        streams_count=3,
        hours=4.5,
        duration_minutes=270,
        last_stream=None,
        hltb_all_styles=20.0,
        steam_url=None,
        cover_url=None,
        liked=True,
        completed=False,
        tags="PC | Action",
    )
    assert view.name == "Hades"
    assert view.liked


def test_game_state_update_requires_both_bools():
    with pytest.raises(Exception):
        GameStateUpdateIn(liked=True)


def test_release_view_defaults():
    view = ReleaseView(
        id=1,
        name="Upcoming",
        release_date=None,
        release_delta_days=None,
        steam_url=None,
        description_ru=None,
        description_en=None,
        cover_url=None,
        interested=False,
        tags="",
        recommenders="",
        recommenders_count=0,
    )
    assert not view.interested


def test_bot_command_create_normalizes_name_and_defaults_bot():
    body = BotCommandCreateIn(name="  !Points  ", description="  Баллы  ")
    assert body.name == "points"
    assert body.description == "Баллы"
    assert body.bot_name == "self"


def test_bot_command_state_update_allows_partial_flags():
    only_visible = BotCommandStateUpdateIn(is_visible=False)
    assert not only_visible.is_visible
    assert only_visible.is_active is None


def test_recommendation_view():
    view = RecommendationView(
        id=1,
        title="Celeste",
        status="released",
        release_date=None,
        steam_url=None,
        igdb_score=88.0,
        cover_url=None,
        description_ru=None,
        description_en=None,
        votes_count=2,
        recommenders="Tabula",
        tags="",
        release_delta_days=None,
    )
    assert view.status == "released"
    assert view.votes_count == 2
