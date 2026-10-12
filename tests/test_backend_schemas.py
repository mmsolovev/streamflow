"""Tests for web schemas (Pydantic DTOs)."""
import unittest

from backend.schemas.common import Page
from backend.schemas.game import GameStateUpdateIn, GameView
from backend.schemas.recommendation import RecommendationView
from backend.schemas.release import ReleaseView


class SchemaTests(unittest.TestCase):
    def test_page_serializes_generic_items(self):
        page = Page[GameView](items=[], total=0, limit=10, offset=0)
        self.assertEqual(page.model_dump(), {"items": [], "total": 0, "limit": 10, "offset": 0})

    def test_game_view_from_dict(self):
        view = GameView(
            id=1,
            name="Hades",
            rank=2,
            streams_count=3,
            hours=4.5,
            last_stream=None,
            hltb_all_styles=20.0,
            steam_url=None,
            liked=True,
            completed=False,
            tags="PC | Action",
        )
        self.assertEqual(view.name, "Hades")
        self.assertTrue(view.liked)

    def test_game_state_update_requires_both_bools(self):
        with self.assertRaises(Exception):
            GameStateUpdateIn(liked=True)

    def test_release_view_defaults(self):
        view = ReleaseView(
            id=1,
            name="Upcoming",
            release_date=None,
            release_delta_days=None,
            steam_url=None,
            description_ru=None,
            interested=False,
            tags="",
            recommenders="",
        )
        self.assertFalse(view.interested)

    def test_recommendation_view(self):
        view = RecommendationView(
            id=1,
            title="Celeste",
            status="released",
            release_date=None,
            steam_url=None,
            igdb_score=88.0,
            cover_url=None,
            votes_count=2,
            recommenders="Tabula",
            release_delta_days=None,
        )
        self.assertEqual(view.status, "released")
        self.assertEqual(view.votes_count, 2)


if __name__ == "__main__":
    unittest.main()