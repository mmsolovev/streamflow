"""Web API tests: routing, serialization and error mapping without a real DB."""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.deps import get_current_user, get_session, get_streamer_id
from backend.repositories import bot_commands as bot_commands_repo
from backend.repositories import games as games_repo
from backend.repositories import hltb as hltb_repo
from backend.repositories import recommendations as recs_repo
from backend.repositories import releases as releases_repo
from backend.repositories import streams as streams_repo
from backend.routers import meta as meta_router

PREFIX = "/api/v1"


class FakeResult:
    def __init__(self, user=None, row=None):
        self._user = user
        self._row = row

    def scalar_one_or_none(self):
        return self._user

    def scalar_one(self):
        return 0

    def all(self):
        return []

    def first(self):
        return self._row


class FakeSession:
    def __init__(self, game=None, user=None, row=None):
        self._game = game
        self._user = user
        self._row = row
        self.committed = False
        self.executed = []
        self.added = []

    async def get(self, model, pk):
        return self._game

    async def execute(self, *args, **kwargs):
        self.executed.append(args[0] if args else None)
        return FakeResult(user=self._user, row=self._row)

    async def commit(self):
        self.committed = True

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    def executed_sql(self) -> str:
        """Все выполненные SQL-запросы одной строкой — для проверок."""
        parts = []
        for stmt in self.executed:
            if stmt is None:
                continue
            try:
                parts.append(str(stmt.compile(compile_kwargs={"literal_binds": True})))
            except Exception:  # noqa: BLE001 — не все объекты компилируются
                parts.append(str(stmt))
        return "\n".join(parts)


ADMIN = SimpleNamespace(
    id=1,
    role="owner",
    is_streamer=True,
    current_profile=SimpleNamespace(login="mishgan_sol", display_name="Mishgan"),
)

# Стример без прав администратора.
STREAMER_ONLY = SimpleNamespace(
    id=2,
    role="streamer",
    is_streamer=True,
    current_profile=SimpleNamespace(login="tabula", display_name="Tabula"),
)

# Обычный авторизованный пользователь.
REGULAR_USER = SimpleNamespace(
    id=3,
    role="user",
    is_streamer=False,
    current_profile=SimpleNamespace(login="viewer", display_name="Viewer"),
)


def _session_dep(session):
    async def _dep():
        yield session

    return _dep


@pytest.fixture()
def client():
    app.dependency_overrides[get_session] = _session_dep(FakeSession())
    app.dependency_overrides[get_current_user] = lambda: ADMIN
    app.dependency_overrides[get_streamer_id] = lambda: 2
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_health_degraded_without_db(client):
    response = client.get(f"{PREFIX}/health")
    assert response.status_code == 200
    assert response.json()["database"] == "ok"


def test_list_games_serializes_hours(client):
    items = [{
        "id": 1,
        "name": "Hades",
        "rank": 1,
        "streams_count": 2,
        "duration_minutes": 90,
        "last_stream": None,
        "hltb_all_styles": 25.0,
        "steam_url": None,
        "cover_url": None,
        "liked": True,
        "completed": False,
        "tags": "PC | Action",
    }]
    with patch.object(
        games_repo,
        "list_games",
        AsyncMock(return_value=(items, 1, 1, {"liked": 0, "completed": 0})),
    ):
        response = client.get(f"{PREFIX}/games")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["hours"] == 1.5
    assert body["items"][0]["liked"]


def test_get_game_not_found_maps_error_envelope(client):
    with patch.object(games_repo, "get_game", AsyncMock(return_value=None)):
        response = client.get(f"{PREFIX}/games/999")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "error"


def test_list_streams(client):
    items = [{
        "id": 1,
        "started_at": "2026-04-05T18:00:00",
        "ended_at": None,
        "duration_minutes": 120,
        "title": "Stream",
        "games": ["Hades"],
        "tags": ["Участники"],
        "participants": [
            {
                "user_id": 1,
                "login": "tabula",
                "display_name": "Tabula",
                "twitch_url": "https://www.twitch.tv/tabula",
            }
        ],
        "vod_url": None,
        "avg_viewers": 10,
        "max_viewers": 20,
    }]
    with patch.object(
        streams_repo,
        "list_streams",
        AsyncMock(return_value=(items, 1, 1, {"total": 1, "with_vod": 0, "total_minutes": 0})),
    ):
        response = client.get(f"{PREFIX}/streams")
    assert response.status_code == 200
    assert response.json()["items"][0]["duration_hours"] == 2.0


def test_channel_info_offline_by_default(client):
    response = client.get(f"{PREFIX}/meta/channel")
    assert response.status_code == 200
    assert not response.json()["is_live"]


def test_channel_info_online_from_collecting_session(client):
    with patch.object(
        meta_router, "_is_channel_live", AsyncMock(return_value=True)
    ):
        response = client.get(f"{PREFIX}/meta/channel")
    assert response.status_code == 200
    assert response.json()["is_live"]


def test_list_bot_commands(client):
    items = [
        {
            "id": 1,
            "name": "игры",
            "description": "Статистика по игре",
            "bot_name": "self",
            "is_visible": True,
            "is_active": True,
        }
    ]
    with patch.object(
        bot_commands_repo,
        "list_bot_commands",
        AsyncMock(return_value=(items, 1, 1, {"total": 1, "bots": 1})),
    ):
        response = client.get(f"{PREFIX}/bot-commands")
    assert response.status_code == 200
    body = response.json()
    assert body["aggregates"] == {"total": 1, "bots": 1}
    assert body["items"][0]["bot_name"] == "self"


def test_add_bot_command_requires_admin(client):
    app.dependency_overrides[get_current_user] = lambda: REGULAR_USER
    response = client.post(
        f"{PREFIX}/bot-commands",
        json={"name": "points", "description": "Баллы", "bot_name": "StreamElements"},
    )
    assert response.status_code == 403


def test_update_bot_command_state(client):
    command = SimpleNamespace(
        id=5,
        name="gpt",
        description="Вопрос к LLM",
        bot_name="self",
        is_visible=True,
        is_active=True,
    )
    session = FakeSession(game=command)
    app.dependency_overrides[get_session] = _session_dep(session)

    response = client.patch(
        f"{PREFIX}/bot-commands/5", json={"is_visible": False}
    )

    assert response.status_code == 200
    body = response.json()
    assert not body["is_visible"]
    assert body["is_active"]
    assert not command.is_visible
    assert session.committed


def test_update_bot_command_not_found(client):
    response = client.patch(
        f"{PREFIX}/bot-commands/999", json={"is_active": False}
    )
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "not_found"


def test_update_bot_command_requires_admin(client):
    app.dependency_overrides[get_current_user] = lambda: REGULAR_USER
    response = client.patch(
        f"{PREFIX}/bot-commands/5", json={"is_active": False}
    )
    assert response.status_code == 403


def test_list_hltb(client):
    items = [{
        "id": 7,
        "name": "Hades",
        "hltb_id": "12782",
        "hltb_name": "Hades",
        "all_styles": 22.5,
        "main_story": 22.5,
        "main_extra": None,
        "completionist": 52.0,
        "coop": None,
        "multiplayer": None,
        "review_score": 90,
    }]
    with patch.object(
        hltb_repo,
        "list_hltb",
        AsyncMock(return_value=(items, 1, 1, {"total": 1, "with_time": 1})),
    ):
        response = client.get(f"{PREFIX}/hltb")
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["hltb_id"] == "12782"
    assert body["items"][0]["all_styles"] == 22.5


def test_list_releases(client):
    items = [{
        "id": 2,
        "name": "Upcoming",
        "release_date": None,
        "release_delta_days": None,
        "steam_url": None,
        "description_ru": None,
        "description_en": None,
        "cover_url": None,
        "interested": False,
        "tags": "",
        "recommenders": "",
        "recommenders_count": 0,
    }]
    with patch.object(
        releases_repo,
        "list_releases",
        AsyncMock(return_value=(items, 1, 1, {"interested": 0, "released": 0})),
    ):
        response = client.get(f"{PREFIX}/releases")
    assert response.status_code == 200
    assert response.json()["items"][0]["name"] == "Upcoming"


def test_list_recommendations(client):
    items = [{
        "id": 3,
        "title": "Celeste",
        "status": "released",
        "release_date": None,
        "release_delta_days": None,
        "steam_url": None,
        "igdb_score": 88.0,
        "cover_url": None,
        "description_ru": None,
        "description_en": None,
        "votes_count": 2,
        "recommenders": "Tabula",
        "tags": "PC",
    }]
    with patch.object(
        recs_repo,
        "list_recommendations",
        AsyncMock(return_value=(items, 1, 1, {"with_score": 0, "votes": 0})),
    ):
        response = client.get(f"{PREFIX}/recommendations")
    assert response.status_code == 200
    assert response.json()["items"][0]["votes_count"] == 2


def test_update_game_streamer_state(client):
    app.dependency_overrides[get_session] = _session_dep(
        FakeSession(game=SimpleNamespace(id=5))
    )
    response = client.patch(
        f"{PREFIX}/games/5/streamer-state",
        json={"liked": True, "completed": False},
    )
    assert response.status_code == 200
    assert response.json() == {"game_id": 5, "liked": True, "completed": False}


def test_update_release_interested(client):
    app.dependency_overrides[get_session] = _session_dep(
        FakeSession(game=SimpleNamespace(id=5))
    )
    response = client.patch(
        f"{PREFIX}/releases/5/interested",
        json={"interested": True},
    )
    assert response.status_code == 200
    assert response.json() == {"game_id": 5, "interested": True}


def test_mark_interested_creates_tabula_recommendation(client):
    """Отметка «Интересно» создаёт рекомендацию Tabula с нужной пометкой."""
    session = FakeSession(
        game=SimpleNamespace(id=5),
        user=SimpleNamespace(id=42),
        row=None,
    )
    app.dependency_overrides[get_session] = _session_dep(session)
    response = client.patch(
        f"{PREFIX}/releases/5/interested",
        json={"interested": True},
    )
    assert response.status_code == 200
    sql = session.executed_sql()
    assert "game_recommendations" in sql
    assert "Ожидаемая новинка по версии Tabula" in sql


def test_unmark_interested_removes_generated_recommendation(client):
    """Снятие отметки удаляет только созданную этой механикой рекомендацию."""
    session = FakeSession(
        game=SimpleNamespace(id=5),
        user=SimpleNamespace(id=42),
        row=SimpleNamespace(recommendation_note="Ожидаемая новинка по версии Tabula"),
    )
    app.dependency_overrides[get_session] = _session_dep(session)
    response = client.patch(
        f"{PREFIX}/releases/5/interested",
        json={"interested": False},
    )
    assert response.status_code == 200
    sql = session.executed_sql()
    assert "DELETE FROM game_recommendations" in sql


def test_write_requires_streamer_or_admin(client):
    app.dependency_overrides.pop(get_current_user)
    response = client.patch(
        f"{PREFIX}/games/5/streamer-state",
        json={"liked": True, "completed": False},
    )
    assert response.status_code == 401


def test_game_state_allows_streamer(client):
    """Стример входит в staff и может редактировать таблицы."""
    app.dependency_overrides[get_current_user] = lambda: STREAMER_ONLY
    app.dependency_overrides[get_session] = _session_dep(
        FakeSession(game=SimpleNamespace(id=5))
    )
    response = client.patch(
        f"{PREFIX}/games/5/streamer-state",
        json={"liked": True, "completed": False},
    )
    assert response.status_code == 200


def test_release_interested_allows_streamer(client):
    """Отметка «Интересно» доступна стримеру как staff."""
    app.dependency_overrides[get_current_user] = lambda: STREAMER_ONLY
    app.dependency_overrides[get_session] = _session_dep(
        FakeSession(game=SimpleNamespace(id=5))
    )
    response = client.patch(
        f"{PREFIX}/releases/5/interested",
        json={"interested": True},
    )
    assert response.status_code == 200


def test_regular_user_cannot_change_flags(client):
    """Обычный пользователь (не админ, не стример) — 403."""
    app.dependency_overrides[get_current_user] = lambda: REGULAR_USER
    app.dependency_overrides[get_session] = _session_dep(
        FakeSession(game=SimpleNamespace(id=5))
    )
    response = client.patch(
        f"{PREFIX}/games/5/streamer-state",
        json={"liked": True, "completed": False},
    )
    assert response.status_code == 403


def test_add_recommendation(client):
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
        response = client.post(f"{PREFIX}/recommendations", json={"query": "Celeste"})
    assert response.status_code == 200
    assert response.json()["outcome"] == "voted"
    assert response.json()["recommendation"]["title"] == "Celeste"


def test_add_recommendation_conflict(client):
    result = SimpleNamespace(
        outcome="already_streamed", recommendation=None, message="already"
    )
    with patch(
        "services.recommendations_service.recommend_game",
        AsyncMock(return_value=result),
    ):
        response = client.post(f"{PREFIX}/recommendations", json={"query": "Hades"})
    assert response.status_code == 409


def test_delete_recommendation(client):
    with patch(
        "backend.routers.recommendations.find_user_recommendation",
        AsyncMock(return_value={"user_id": 1, "game_id": 7}),
    ), patch(
        "backend.routers.recommendations.remove_recommendation",
        AsyncMock(return_value=None),
    ):
        response = client.delete(f"{PREFIX}/recommendations/7")
    assert response.status_code == 200
    assert response.json()["outcome"] == "deleted"


def test_me_unauthorized_without_cookie(client):
    app.dependency_overrides.pop(get_current_user)
    response = client.get(f"{PREFIX}/auth/me")
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "unauthorized"


def test_login_not_configured_returns_503(client):
    settings = SimpleNamespace(
        twitch_client_id=None,
        twitch_client_secret=None,
        twitch_redirect_uri=None,
    )
    with patch("backend.routers.auth.get_backend_settings", return_value=settings):
        response = client.get(f"{PREFIX}/auth/login")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "oauth_not_configured"


def test_login_redirects_to_twitch_when_configured(client):
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
        response = client.get(f"{PREFIX}/auth/login", follow_redirects=False)
    assert response.status_code == 307
    assert (
        response.headers["location"]
        == "https://id.twitch.tv/oauth2/authorize?state=abc"
    )
    assert "backend_oauth_state" in response.cookies


def test_callback_rejects_bad_state(client):
    settings = SimpleNamespace(backend_oauth_state_cookie_name="backend_oauth_state")
    with patch("backend.routers.auth.get_backend_settings", return_value=settings):
        client.cookies.set("backend_oauth_state", "expected")
        response = client.get(f"{PREFIX}/auth/callback?code=x&state=wrong")
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_oauth_state"
