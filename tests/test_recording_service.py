"""Тесты единого реестра записей (`stream_recordings`).

Проверяются чистые функции: разбор ссылки/длительности и нормализация
времени. Логика БД (upsert/deactivate) опирается на них, поэтому ошибка
здесь стоила бы дублей VOD или потерянной истории.

Запуск:
    .venv\\Scripts\\python.exe -m pytest tests/test_recording_service.py -q
"""

from datetime import datetime, timezone

from services.recording_service import (
    fields_from_vod,
    parse_duration_minutes,
    parse_video_id,
    to_naive_utc,
)


def test_standard_url():
    assert parse_video_id("https://www.twitch.tv/videos/2915709311") == "2915709311"


def test_url_with_query_and_slash():
    assert parse_video_id("https://www.twitch.tv/videos/2915709311?t=1h") == "2915709311"
    assert parse_video_id("https://www.twitch.tv/videos/2915709311/") == "2915709311"


def test_channel_scoped_url():
    assert parse_video_id("https://www.twitch.tv/tabula/videos/2915709311") == "2915709311"


def test_no_video_id():
    assert parse_video_id("https://www.twitch.tv/tabula") is None
    assert parse_video_id("") is None
    assert parse_video_id(None) is None


def test_hours_minutes_seconds():
    assert parse_duration_minutes("2h3m4s") == 123


def test_short_forms():
    assert parse_duration_minutes("45m0s") == 45
    assert parse_duration_minutes("1h") == 60
    assert parse_duration_minutes("0h5m0s") == 5


def test_rounds_half_up():
    # 62.5 минуты не должны превращаться в 62: запись «короче» реальной.
    assert parse_duration_minutes("1h2m30s") == 63


def test_seconds_are_rounded_to_minutes():
    assert parse_duration_minutes(90) == 2


def test_zero_and_garbage_are_none():
    assert parse_duration_minutes("0s") is None
    assert parse_duration_minutes("неизвестно") is None
    assert parse_duration_minutes(None) is None


def test_iso_with_z():
    assert to_naive_utc("2026-10-31T12:59:27Z") == datetime(2026, 10, 31, 12, 59, 27)


def test_iso_with_offset():
    assert to_naive_utc("2026-10-31T12:00:00+03:00") == datetime(2026, 10, 31, 9, 0)


def test_naive_stays_as_is():
    naive = datetime(2026, 10, 31, 12, 0)
    assert to_naive_utc(naive) == naive


def test_aware_datetime():
    aware = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc)
    assert to_naive_utc(aware) == datetime(2026, 10, 31, 12, 0)


def test_empty_and_garbage_are_none():
    assert to_naive_utc(None) is None
    assert to_naive_utc("") is None
    assert to_naive_utc("not-a-date") is None


def test_helix_payload():
    fields = fields_from_vod(
        {
            "id": "2915709311",
            "stream_id": "319021408871",
            "url": "https://www.twitch.tv/videos/2915709311",
            "duration": "4h16m7s",
            "created_at": "2026-10-31T16:59:27Z",
        }
    )

    assert fields["twitch_video_id"] == "2915709311"
    assert fields["twitch_stream_id"] == "319021408871"
    assert fields["duration_minutes"] == 256
    assert fields["recorded_at"] == datetime(2026, 10, 31, 16, 59, 27)
    assert fields["url"] == "https://www.twitch.tv/videos/2915709311"


def test_video_id_is_parsed_from_url_when_missing():
    fields = fields_from_vod({"url": "https://www.twitch.tv/videos/123"})
    assert fields["twitch_video_id"] == "123"


def test_broadcast_zero_is_none():
    # Twitch отдаёт "0" для записей без broadcast — это не id стрима.
    assert fields_from_vod({"stream_id": "0"})["twitch_stream_id"] is None


def test_published_at_used_as_fallback():
    fields = fields_from_vod({"published_at": "2026-10-31T12:00:00Z"})
    assert fields["recorded_at"] == datetime(2026, 10, 31, 12, 0)


def test_empty_payload():
    fields = fields_from_vod({})
    assert fields["url"] is None
    assert fields["twitch_video_id"] is None
    assert fields["duration_minutes"] is None
