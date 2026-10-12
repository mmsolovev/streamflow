"""Web API tests: routing, serialization and error mapping without a real DB."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from backend.app import app
from backend.deps import get_current_user, get_session
from backend.repositories import games as games_repo
from backend.repositories import recommendations as recs_repo
from backend.repositories import releases as releases_repo
from backend.repositories import streams as streams_repo

PREFIX = "/api/v1"


class FakeResult:
    def scalar_one_or_none(self):
        return None

    def scalar_one(self):
        return 0

    def all(self):
        return []

    def first(self):
        return None


class FakeSession:
    def __init__(self, game=None):
        self._game = game
        self.committed = False

    async def get(self, model, pk):
        return self._game

    async def execute(self, *args, **kwargs):
        return FakeResult()

    async def commit(self):
        self.committed = True


ADMIN = SimpleNamespace(
    id=1,
    is_streamer=True,
    is_admin=True,
    current_profile=SimpleNamespace(login="mishgan_sol", display_name="Mishgan"),
)


def _session_dep(session):
    async def _dep():
        yield session

    return _dep


class WebApiTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        app.dependency_overrides[get_session] = _session_dep(FakeSession())
        app.dependency_overrides[get_current_user] = lambda: ADMIN
        self.addCleanup(app.dependency_overrides.clear)

    def test_health_degraded_without_db(self):
        response = self.client.get(f"{PREFIX}/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["database"], "ok")

    def test_list_games_serializes_hours(self):
        items = [{
            "id": 1,
            "name": "Hades",
            "rank": 1,
            "streams_count": 2,
            "duration_minutes": 90,
            "last_stream": None,
            "hltb_all_styles": 25.0,
            "steam_url": None,
            "liked": True,
            "completed": False,
            "tags": "PC | Action",
        }]
        with patch.object(games_repo, "list_games", AsyncMock(return_value=(items, 1))):
            response = self.client.get(f"{PREFIX}/games")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["total"], 1)
        self.assertEqual(body["items"][0]["hours"], 1.5)
        self.assertTrue(body["items"][0]["liked"])

    def test_get_game_not_found_maps_error_envelope(self):
        with patch.object(games_repo, "get_game", AsyncMock(return_value=None)):
            response = self.client.get(f"{PREFIX}/games/999")
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["detail"]["code"], "error")

    def test_list_streams(self):
        items = [{
            "id": 1,
            "started_at": "2026-04-05T18:00:00",
            "ended_at": None,
            "duration_minutes": 120,
            "title": "Stream",
            "games": ["Hades"],
            "tags": ["Участники"],
            "participants": ["Tabula"],
            "vod_url": None,
            "avg_viewers": 10,
            "max_viewers": 20,
        }]
        with patch.object(streams_repo, "list_streams", AsyncMock(return_value=(items, 1))):
            response = self.client.get(f"{PREFIX}/streams")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["duration_hours"], 2.0)

    def test_list_releases(self):
        items = [{
            "id": 2,
            "name": "Upcoming",
            "release_date": None,
            "release_delta_days": None,
            "steam_url": None,
            "description_ru": None,
            "interested": False,
            "tags": "",
            "recommenders": "",
        }]
        with patch.object(releases_repo, "list_releases", AsyncMock(return_value=(items, 1))):
            response = self.client.get(f"{PREFIX}/releases")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["name"], "Upcoming")

    def test_list_recommendations(self):
        items = [{
            "id": 3,
            "title": "Celeste",
            "status": "released",
            "release_date": None,
            "release_delta_days": None,
            "steam_url": None,
            "igdb_score": 88.0,
            "cover_url": None,
            "votes_count": 2,
            "recommenders": "Tabula",
            "tags": "PC",
        }]
        with patch.object(recs_repo, "list_recommendations", AsyncMock(return_value=(items, 1))):
            response = self.client.get(f"{PREFIX}/recommendations")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["items"][0]["votes_count"], 2)

    def test_update_game_streamer_state(self):
        app.dependency_overrides[get_session] = _session_dep(FakeSession(game=SimpleNamespace(id=5)))
        response = self.client.patch(
            f"{PREFIX}/games/5/streamer-state",
            json={"liked": True, "completed": False},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"game_id": 5, "liked": True, "completed": False})

    def test_update_release_interested(self):
        app.dependency_overrides[get_session] = _session_dep(FakeSession(game=SimpleNamespace(id=5)))
        response = self.client.patch(
            f"{PREFIX}/releases/5/interested",
            json={"interested": True},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"game_id": 5, "interested": True})

    def test_write_requires_streamer_or_admin(self):
        app.dependency_overrides.pop(get_current_user)
        response = self.client.patch(
            f"{PREFIX}/games/5/streamer-state",
            json={"liked": True, "completed": False},
        )
        self.assertEqual(response.status_code, 401)

    def test_add_recommendation(self):
        summary = SimpleNamespace(
            id=7,
            title="Celeste",
            status="released",
            release_date=None,
            steam_url=None,
            igdb_score=90.0,
            cover_url=None,
            votes_count=1,
            recommenders=["Mishgan"],
        )
        result = SimpleNamespace(outcome="voted", recommendation=summary, message="ok")
        with patch(
            "services.recommendations_service.recommend_game",
            AsyncMock(return_value=result),
        ):
            response = self.client.post(f"{PREFIX}/recommendations", json={"query": "Celeste"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["outcome"], "voted")
        self.assertEqual(response.json()["recommendation"]["title"], "Celeste")

    def test_add_recommendation_conflict(self):
        result = SimpleNamespace(outcome="already_streamed", recommendation=None, message="already")
        with patch(
            "services.recommendations_service.recommend_game",
            AsyncMock(return_value=result),
        ):
            response = self.client.post(f"{PREFIX}/recommendations", json={"query": "Hades"})
        self.assertEqual(response.status_code, 409)

    def test_delete_recommendation(self):
        with patch(
            "backend.routers.recommendations.find_user_recommendation",
            AsyncMock(return_value={"user_id": 1, "game_id": 7}),
        ), patch(
            "backend.routers.recommendations.remove_recommendation",
            AsyncMock(return_value=None),
        ):
            response = self.client.delete(f"{PREFIX}/recommendations/7")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["outcome"], "deleted")

    def test_me_unauthorized_without_cookie(self):
        app.dependency_overrides.pop(get_current_user)
        response = self.client.get(f"{PREFIX}/auth/me")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"]["code"], "unauthorized")

    def test_login_not_configured_returns_503(self):
        settings = SimpleNamespace(
            twitch_client_id=None,
            twitch_client_secret=None,
            twitch_redirect_uri=None,
        )
        with patch("backend.routers.auth.get_backend_settings", return_value=settings):
            response = self.client.get(f"{PREFIX}/auth/login")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"]["code"], "oauth_not_configured")

    def test_login_redirects_to_twitch_when_configured(self):
        settings = SimpleNamespace(
            twitch_client_id="cid",
            twitch_client_secret="secret",
            twitch_redirect_uri="http://127.0.0.1:8001/api/v1/auth/callback",
            backend_oauth_state_cookie_name="backend_oauth_state",
            backend_cookie_secure=False,
            twitch_oauth_state_ttl_seconds=600,
        )
        with patch("backend.routers.auth.get_backend_settings", return_value=settings), patch(
            "backend.security.sessions.get_backend_settings", return_value=settings
        ), patch(
            "backend.routers.auth.build_authorize_url",
            return_value="https://id.twitch.tv/oauth2/authorize?state=abc",
        ):
            client = TestClient(app)
            response = client.get(f"{PREFIX}/auth/login", follow_redirects=False)
        self.assertEqual(response.status_code, 307)
        self.assertEqual(
            response.headers["location"],
            "https://id.twitch.tv/oauth2/authorize?state=abc",
        )
        self.assertIn("backend_oauth_state", response.cookies)

    def test_callback_rejects_bad_state(self):
        settings = SimpleNamespace(backend_oauth_state_cookie_name="backend_oauth_state")
        with patch("backend.routers.auth.get_backend_settings", return_value=settings):
            client = TestClient(app)
            client.cookies.set("backend_oauth_state", "expected")
            response = client.get(f"{PREFIX}/auth/callback?code=x&state=wrong")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["detail"]["code"], "invalid_oauth_state")


if __name__ == "__main__":
    unittest.main()