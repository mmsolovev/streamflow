from datetime import datetime

from runtime.collector import RuntimeStreamCollector
from services import game_metadata_service
from services.game_metadata_service import is_non_igdb_category
import services.twitch_service as twitch_service


class _FakeResponse:
    status = 200

    def __init__(self, payload):
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def json(self):
        return self.payload

    async def text(self):
        return ""


class _FakeClientSession:
    calls = []
    payload = {}

    def __init__(self, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def get(self, url, *, headers, params):
        self.calls.append((url, headers, params))
        return _FakeResponse(self.payload)


async def test_helix_category_lookup_returns_igdb_id(monkeypatch):
    _FakeClientSession.calls.clear()
    _FakeClientSession.payload = {
        "data": [
            {
                "id": "509658",
                "name": "Just Chatting",
                "igdb_id": "",
                "box_art_url": "https://example.test/boxart",
            }
        ]
    }
    monkeypatch.setattr(twitch_service, "_game_cache", {})
    monkeypatch.setattr(twitch_service, "get_app_access_token", _fake_token)
    monkeypatch.setattr(twitch_service.aiohttp, "ClientSession", _FakeClientSession)

    result = await twitch_service.get_game_by_category_id("509658")
    cached = await twitch_service.get_game_by_category_id("509658")

    assert result == {
        "id": "509658",
        "name": "Just Chatting",
        "igdb_id": None,
        "box_art_url": "https://example.test/boxart",
    }
    assert cached == result
    assert len(_FakeClientSession.calls) == 1
    assert _FakeClientSession.calls[0][2] == {"id": "509658"}


async def _fake_token():
    return "test-token"


def test_non_game_categories_are_excluded_from_igdb_search():
    assert is_non_igdb_category("Just Chatting")
    assert is_non_igdb_category("Science & Technology")
    assert not is_non_igdb_category("Bayonetta")


async def test_igdb_lookup_prefers_twitch_id_and_falls_back_only_when_missing(
    monkeypatch,
):
    calls = []
    expected = object()

    async def by_id(value):
        calls.append(("id", value))
        return expected

    async def by_name(value):
        calls.append(("name", value))
        return expected

    monkeypatch.setattr(game_metadata_service, "fetch_igdb_metadata_by_id", by_id)
    monkeypatch.setattr(game_metadata_service, "fetch_igdb_metadata", by_name)

    direct = await game_metadata_service._fetch_igdb_metadata(
        igdb_id="1234",
        category_name="Example",
        non_game=False,
    )
    fallback = await game_metadata_service._fetch_igdb_metadata(
        igdb_id=None,
        category_name="Fallback title",
        non_game=False,
    )
    skipped = await game_metadata_service._fetch_igdb_metadata(
        igdb_id=None,
        category_name="Just Chatting",
        non_game=True,
    )

    assert direct is expected
    assert fallback is expected
    assert skipped is None
    assert calls == [("id", "1234"), ("name", "Fallback title")]


def test_category_id_change_with_same_name_is_a_real_category_change():
    collector = RuntimeStreamCollector.__new__(RuntimeStreamCollector)
    collector.active_session = {
        "collector": {},
        "category_name": "Bayonetta",
        "category_id": "old-id",
        "category_history": [],
        "game_segments": [
            {
                "category_name": "Bayonetta",
                "category_id": "old-id",
                "started_at": "2026-11-19T10:00:00+00:00",
                "ended_at": None,
            }
        ],
    }

    changed = collector._apply_channel_update(
        title=None,
        category_name="Bayonetta",
        category_id="new-id",
        changed_at=datetime(2026, 11, 19, 10, 5),
    )

    assert changed is True
    assert collector.active_session["category_id"] == "new-id"
    assert len(collector.active_session["game_segments"]) == 2
