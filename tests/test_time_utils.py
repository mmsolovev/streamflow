"""Тесты единого времени: TwitchTracker (локальное) ↔ БД (naive UTC).

Запуск:
    .venv\\Scripts\\python.exe -m pytest tests/test_time_utils.py -q
"""

from datetime import date, datetime, timedelta, timezone

import pytest

import config.settings as settings
from utils.time_utils import tracker_timezone, tracker_to_utc, utc_to_tracker


@pytest.fixture(autouse=True)
def tt_timezone(monkeypatch):
    """Подменяет пояс TT, не трогая .env и lru_cache навсегда.

    По умолчанию — Europe/Moscow; тестам с другим поясом передаётся
    возвращённая функция.
    """

    def _set(name: str) -> None:
        monkeypatch.setattr(settings, "TWITCHTRACKER_TIMEZONE", name)
        tracker_timezone.cache_clear()

    _set("Europe/Moscow")
    yield _set
    tracker_timezone.cache_clear()


def test_moscow_naive_is_shifted_back_three_hours():
    local = datetime(2026, 10, 31, 12, 43, 10)
    assert tracker_to_utc(local) == datetime(2026, 10, 31, 9, 43, 10)


def test_utc_timezone_is_identity(tt_timezone):
    tt_timezone("UTC")
    local = datetime(2026, 10, 31, 12, 0)
    assert tracker_to_utc(local) == local


def test_aware_value_is_converted_to_utc():
    aware = datetime(2026, 10, 31, 12, 0, tzinfo=timezone(timedelta(hours=3)))
    assert tracker_to_utc(aware) == datetime(2026, 10, 31, 9, 0)


def test_tracker_to_utc_none_passthrough():
    assert tracker_to_utc(None) is None


def test_result_is_naive():
    converted = tracker_to_utc(datetime(2026, 10, 31, 12, 0))
    assert converted.tzinfo is None


def test_roundtrip():
    local = datetime(2026, 10, 31, 12, 43, 10)
    assert utc_to_tracker(tracker_to_utc(local)) == local


def test_utc_time_is_shifted_forward():
    utc = datetime(2026, 10, 31, 9, 0)
    assert utc_to_tracker(utc) == datetime(2026, 10, 31, 12, 0)


def test_utc_to_tracker_none_passthrough():
    assert utc_to_tracker(None) is None


def test_unknown_zone_falls_back_to_moscow(tt_timezone):
    """Windows без пакета tzdata не должен ронять импорт."""
    tt_timezone("Unknown/Nowhere")
    local = datetime(2026, 10, 31, 12, 0)
    assert tracker_to_utc(local) == datetime(2026, 10, 31, 9, 0)


def test_stream_timestamp_is_converted_to_utc():
    # Импорт здесь, а не сверху: модуль тянет BeautifulSoup/настройки.
    from pipeline.ingest.twitchtracker_parser import _parse_stream_timestamp

    parsed = _parse_stream_timestamp("Thu, Aug 13, 12:45")

    assert parsed == datetime(date.today().year, 8, 13, 9, 45)


def test_unparseable_returns_none():
    from pipeline.ingest.twitchtracker_parser import _parse_stream_timestamp

    assert _parse_stream_timestamp("not a date") is None
