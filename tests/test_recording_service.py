"""Тесты единого реестра записей (`stream_recordings`).

Проверяются чистые функции: разбор ссылки/длительности и нормализация
времени. Логика БД (upsert/deactivate) опирается на них, поэтому ошибка
здесь стоила бы дублей VOD или потерянной истории.

Запуск:
    .venv\\Scripts\\python.exe -m unittest discover -s tests -t .
"""

import unittest
from datetime import datetime, timezone

from services.recording_service import (
    fields_from_vod,
    parse_duration_minutes,
    parse_video_id,
    to_naive_utc,
)


class ParseVideoIdTests(unittest.TestCase):
    def test_standard_url(self):
        self.assertEqual(
            parse_video_id("https://www.twitch.tv/videos/2915709311"),
            "2915709311",
        )

    def test_url_with_query_and_slash(self):
        self.assertEqual(
            parse_video_id("https://www.twitch.tv/videos/2915709311?t=1h"),
            "2915709311",
        )
        self.assertEqual(
            parse_video_id("https://www.twitch.tv/videos/2915709311/"),
            "2915709311",
        )

    def test_channel_scoped_url(self):
        self.assertEqual(
            parse_video_id("https://www.twitch.tv/tabula/videos/2915709311"),
            "2915709311",
        )

    def test_no_video_id(self):
        self.assertIsNone(parse_video_id("https://www.twitch.tv/tabula"))
        self.assertIsNone(parse_video_id(""))
        self.assertIsNone(parse_video_id(None))


class ParseDurationMinutesTests(unittest.TestCase):
    def test_hours_minutes_seconds(self):
        self.assertEqual(parse_duration_minutes("2h3m4s"), 123)

    def test_short_forms(self):
        self.assertEqual(parse_duration_minutes("45m0s"), 45)
        self.assertEqual(parse_duration_minutes("1h"), 60)
        self.assertEqual(parse_duration_minutes("0h5m0s"), 5)

    def test_rounds_half_up(self):
        # 62.5 минуты не должны превращаться в 62: запись «короче» реальной.
        self.assertEqual(parse_duration_minutes("1h2m30s"), 63)

    def test_seconds_are_rounded_to_minutes(self):
        self.assertEqual(parse_duration_minutes(90), 2)

    def test_zero_and_garbage_are_none(self):
        self.assertEqual(parse_duration_minutes("0s"), None)
        self.assertEqual(parse_duration_minutes("неизвестно"), None)
        self.assertIsNone(parse_duration_minutes(None))


class ToNaiveUtcTests(unittest.TestCase):
    def test_iso_with_z(self):
        self.assertEqual(
            to_naive_utc("2026-10-31T12:59:27Z"),
            datetime(2026, 10, 31, 12, 59, 27),
        )

    def test_iso_with_offset(self):
        self.assertEqual(
            to_naive_utc("2026-10-31T12:00:00+03:00"),
            datetime(2026, 10, 31, 9, 0),
        )

    def test_naive_stays_as_is(self):
        naive = datetime(2026, 10, 31, 12, 0)
        self.assertEqual(to_naive_utc(naive), naive)

    def test_aware_datetime(self):
        aware = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(to_naive_utc(aware), datetime(2026, 10, 31, 12, 0))

    def test_empty_and_garbage_are_none(self):
        self.assertIsNone(to_naive_utc(None))
        self.assertIsNone(to_naive_utc(""))
        self.assertIsNone(to_naive_utc("not-a-date"))


class FieldsFromVodTests(unittest.TestCase):
    def test_helix_payload(self):
        fields = fields_from_vod(
            {
                "id": "2915709311",
                "stream_id": "319021408871",
                "url": "https://www.twitch.tv/videos/2915709311",
                "duration": "4h16m7s",
                "created_at": "2026-10-31T16:59:27Z",
            }
        )

        self.assertEqual(fields["twitch_video_id"], "2915709311")
        self.assertEqual(fields["twitch_stream_id"], "319021408871")
        self.assertEqual(fields["duration_minutes"], 256)
        self.assertEqual(fields["recorded_at"], datetime(2026, 10, 31, 16, 59, 27))
        self.assertEqual(fields["url"], "https://www.twitch.tv/videos/2915709311")

    def test_video_id_is_parsed_from_url_when_missing(self):
        fields = fields_from_vod({"url": "https://www.twitch.tv/videos/123"})
        self.assertEqual(fields["twitch_video_id"], "123")

    def test_broadcast_zero_is_none(self):
        # Twitch отдаёт "0" для записей без broadcast — это не id стрима.
        self.assertIsNone(fields_from_vod({"stream_id": "0"})["twitch_stream_id"])

    def test_published_at_used_as_fallback(self):
        fields = fields_from_vod({"published_at": "2026-10-31T12:00:00Z"})
        self.assertEqual(fields["recorded_at"], datetime(2026, 10, 31, 12, 0))

    def test_empty_payload(self):
        fields = fields_from_vod({})
        self.assertIsNone(fields["url"])
        self.assertIsNone(fields["twitch_video_id"])
        self.assertIsNone(fields["duration_minutes"])


if __name__ == "__main__":
    unittest.main()
