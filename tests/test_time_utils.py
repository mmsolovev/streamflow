"""Тесты единого времени: TwitchTracker (локальное) ↔ БД (naive UTC).

Запуск:
    .venv\\Scripts\\python.exe -m unittest discover -s tests -t .
"""

import unittest
from datetime import date, datetime, timedelta, timezone

import config.settings as settings
from utils.time_utils import tracker_timezone, tracker_to_utc, utc_to_tracker


class _TimezoneCase(unittest.TestCase):
    """Подменяет пояс TT, не трогая .env и lru_cache навсегда."""

    timezone_name = "Europe/Moscow"

    def setUp(self) -> None:
        self._original = settings.TWITCHTRACKER_TIMEZONE
        settings.TWITCHTRACKER_TIMEZONE = self.timezone_name
        tracker_timezone.cache_clear()

    def tearDown(self) -> None:
        settings.TWITCHTRACKER_TIMEZONE = self._original
        tracker_timezone.cache_clear()


class TrackerToUtcTests(_TimezoneCase):
    def test_moscow_naive_is_shifted_back_three_hours(self):
        local = datetime(2026, 10, 31, 12, 43, 10)
        self.assertEqual(tracker_to_utc(local), datetime(2026, 10, 31, 9, 43, 10))

    def test_utc_timezone_is_identity(self):
        settings.TWITCHTRACKER_TIMEZONE = "UTC"
        tracker_timezone.cache_clear()
        local = datetime(2026, 10, 31, 12, 0)
        self.assertEqual(tracker_to_utc(local), local)

    def test_aware_value_is_converted_to_utc(self):
        aware = datetime(2026, 10, 31, 12, 0, tzinfo=timezone(timedelta(hours=3)))
        self.assertEqual(tracker_to_utc(aware), datetime(2026, 10, 31, 9, 0))

    def test_none_passthrough(self):
        self.assertIsNone(tracker_to_utc(None))

    def test_result_is_naive(self):
        converted = tracker_to_utc(datetime(2026, 10, 31, 12, 0))
        self.assertIsNone(converted.tzinfo)


class UtcToTrackerTests(_TimezoneCase):
    def test_roundtrip(self):
        local = datetime(2026, 10, 31, 12, 43, 10)
        self.assertEqual(utc_to_tracker(tracker_to_utc(local)), local)

    def test_utc_time_is_shifted_forward(self):
        utc = datetime(2026, 10, 31, 9, 0)
        self.assertEqual(utc_to_tracker(utc), datetime(2026, 10, 31, 12, 0))

    def test_none_passthrough(self):
        self.assertIsNone(utc_to_tracker(None))


class FallbackTimezoneTests(_TimezoneCase):
    """Windows без пакета tzdata не должен ронять импорт."""

    timezone_name = "Unknown/Nowhere"

    def test_unknown_zone_falls_back_to_moscow(self):
        local = datetime(2026, 10, 31, 12, 0)
        self.assertEqual(tracker_to_utc(local), datetime(2026, 10, 31, 9, 0))


class TrackerTimestampParseTests(_TimezoneCase):
    def test_stream_timestamp_is_converted_to_utc(self):
        # Импорт здесь, а не сверху: модуль тянет BeautifulSoup/настройки.
        from pipeline.ingest.twitchtracker_parser import _parse_stream_timestamp

        parsed = _parse_stream_timestamp("Thu, Aug 13, 12:45")

        self.assertEqual(
            parsed,
            datetime(date.today().year, 8, 13, 9, 45),
        )

    def test_unparseable_returns_none(self):
        from pipeline.ingest.twitchtracker_parser import _parse_stream_timestamp

        self.assertIsNone(_parse_stream_timestamp("not a date"))


if __name__ == "__main__":
    unittest.main()
