"""Game review link validation and API tests."""
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from backend.app import app
from backend.deps import get_current_user, get_session
from backend.repositories.games import list_games
from backend.repositories.list_query import ListQuery
from backend.schemas.game import GameReviewsUpdateIn


class FakeSession:
    def __init__(self, game):
        self.game = game
        self.committed = False

    async def get(self, model, game_id):
        return self.game if self.game.id == game_id else None

    async def commit(self):
        self.committed = True


class QueryResult:
    def scalar_one(self):
        return 0

    def all(self):
        return []


class QuerySession:
    def __init__(self):
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return QueryResult()


def test_game_review_links_accept_custom_titles_and_deduplicate_urls():
    links = GameReviewsUpdateIn(
        links=[
            {"title": "Telegram", "url": " https://t.me/channel/123 "},
            {"title": "Twitch", "url": "https://clips.twitch.tv/ExampleClip"},
            {"title": "YouTube", "url": "https://www.youtube.com/shorts/abc123"},
            {"title": "Дубль", "url": "https://t.me/channel/123"},
        ]
    )
    assert [link.model_dump() for link in links.links] == [
        {"title": "Telegram", "url": "https://t.me/channel/123"},
        {"title": "Twitch", "url": "https://clips.twitch.tv/ExampleClip"},
        {"title": "YouTube", "url": "https://www.youtube.com/shorts/abc123"},
    ]


def test_game_review_links_reject_insecure_urls_and_blank_titles():
    for link in (
        {"title": "Telegram", "url": "http://t.me/channel/123"},
        {"title": "   ", "url": "https://example.com/post"},
    ):
        try:
            GameReviewsUpdateIn(links=[link])
        except ValueError:
            continue
        raise AssertionError(f"Expected validation error for {link}")


def test_review_filter_adds_json_array_presence_condition():
    import asyncio

    session = QuerySession()
    asyncio.run(
        list_games(
            session,
            streamer_id=1,
            limit=10,
            offset=0,
            query=ListQuery(filters=["review"]),
        )
    )
    filtered_query = str(
        session.statements[1].compile(dialect=postgresql.dialect())
    )
    assert "jsonb_array_length" in filtered_query
    assert "review_links" in filtered_query


def test_update_game_reviews_saves_links_and_requires_edit_permission():
    game = SimpleNamespace(id=5, review_links=[])
    session = FakeSession(game)

    async def session_dep():
        yield session

    app.dependency_overrides[get_session] = session_dep
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=1,
        role="editor",
        is_streamer=False,
        current_profile=SimpleNamespace(login="editor", display_name="Editor"),
    )
    try:
        response = TestClient(app).patch(
            "/api/v1/games/5/reviews",
            json={"links": [{"title": "Telegram", "url": "https://t.me/channel/123"}]},
        )
        assert response.status_code == 200
        assert response.json() == {
            "game_id": 5,
            "links": [{"title": "Telegram", "url": "https://t.me/channel/123"}],
        }
        assert game.review_links == [
            {"title": "Telegram", "url": "https://t.me/channel/123"}
        ]
        assert session.committed

        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
            id=2,
            role="user",
            is_streamer=False,
            current_profile=SimpleNamespace(login="viewer", display_name="Viewer"),
        )
        denied = TestClient(app).patch(
            "/api/v1/games/5/reviews",
            json={"links": []},
        )
        assert denied.status_code == 403
    finally:
        app.dependency_overrides.clear()
