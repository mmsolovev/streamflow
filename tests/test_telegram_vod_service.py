"""Тесты выбора VOD по stream_id.

Запуск:
    .venv\\Scripts\\python.exe -m pytest tests/test_telegram_vod_service.py -q
"""

from telegram.vod_service import (  # noqa: E402  (внутренние функции проверяются намеренно)
    _duration_minutes,
    _duration_seconds,
    _vod_url,
    pick_vod_for_stream,
    pick_vods_for_stream,
)


def _pick(vods, stream_id):
    """pick_vod_for_stream возвращает Optional — проверяем явно."""
    chosen = pick_vod_for_stream(vods, stream_id)
    assert chosen is not None
    return chosen


def test_exact_stream_id_match():
    vods = [
        {"id": "1", "stream_id": "999", "url": "https://twitch.tv/videos/1"},
        {"id": "2", "stream_id": "123456", "url": "https://twitch.tv/videos/2"},
    ]
    assert _pick(vods, "123456")["id"] == "2"


def test_no_match_returns_none():
    vods = [{"id": "1", "stream_id": "999", "url": "https://twitch.tv/videos/1"}]
    assert pick_vod_for_stream(vods, "123456") is None


def test_empty_list():
    assert pick_vod_for_stream([], "123456") is None


def test_stream_id_compared_as_string():
    # Twitch отдаёт stream_id строкой, сессии тоже; int-гипотеза тут ломается.
    vods = [{"id": "1", "stream_id": "123456", "url": "https://twitch.tv/videos/1"}]
    assert pick_vod_for_stream(vods, "123456") is not None


def test_no_prefix_confusion():
    # stream_id 123 не должен матчить VOD потока 123456.
    vods = [{"id": "1", "stream_id": "123456", "url": "https://twitch.tv/videos/1"}]
    assert pick_vod_for_stream(vods, "123") is None


def test_longest_candidate_wins():
    # Twitch иногда отдаёт повторную обработку; полная запись — самая длинная.
    vods = [
        {"id": "1", "stream_id": "123456", "duration": "10m0s", "url": "https://twitch.tv/videos/1"},
        {"id": "2", "stream_id": "123456", "duration": "2h0m0s", "url": "https://twitch.tv/videos/2"},
        {"id": "3", "stream_id": "123456", "duration": "1h0m0s", "url": "https://twitch.tv/videos/3"},
    ]
    assert _pick(vods, "123456")["id"] == "2"


def test_all_vods_for_broadcast_are_returned_in_chronological_order():
    vods = [
        {
            "id": "2",
            "stream_id": "123456",
            "created_at": "2026-10-01T22:00:00Z",
            "url": "https://twitch.tv/videos/2",
        },
        {
            "id": "1",
            "stream_id": "123456",
            "created_at": "2026-10-01T21:00:00Z",
            "url": "https://twitch.tv/videos/1",
        },
        {
            "id": "3",
            "stream_id": "999999",
            "created_at": "2026-10-01T20:00:00Z",
            "url": "https://twitch.tv/videos/3",
        },
    ]

    assert [vod["id"] for vod in pick_vods_for_stream(vods, "123456")] == ["1", "2"]


def test_duration_hours_minutes_seconds():
    assert _duration_seconds("2h3m4s") == 2 * 3600 + 3 * 60 + 4


def test_duration_short_forms():
    assert _duration_seconds("45m0s") == 2700
    assert _duration_seconds("1h0m0s") == 3600


def test_duration_unparseable_is_zero():
    assert _duration_seconds("неизвестно") == 0
    assert _duration_seconds(None) == 0


def test_duration_numeric_passthrough():
    assert _duration_seconds(90) == 90


def test_minutes_rounded():
    assert _duration_minutes("1h2m30s") == 63
    assert _duration_minutes("10m0s") == 10


def test_zero_minutes_is_none():
    # Нулевая длительность — это «неизвестно», а не «запись нулевой длины».
    assert _duration_minutes("0s") is None


def test_explicit_url_wins():
    assert _vod_url(
        {"id": "1", "url": "https://www.twitch.tv/videos/1", "channel_login": "tabula"}
    ) == "https://www.twitch.tv/videos/1"


def test_built_from_id_and_login():
    assert _vod_url({"id": "1", "channel_login": "tabula"}) == (
        "https://www.twitch.tv/tabula/videos/1"
    )


def test_none_without_id_or_login():
    assert _vod_url({"channel_login": "tabula"}) is None
    assert _vod_url({"id": "1"}) is None
