"""Тесты utils.time_format: форматирование часов/минут.

Запуск:
    .venv\\Scripts\\python.exe -m pytest tests/test_utils_time_format.py -q
"""
from utils.time_format import format_duration_compact, format_hours_minutes


def test_hours_minutes_none():
    assert format_hours_minutes(None) is None


def test_hours_minutes_whole_hours():
    assert format_hours_minutes(2) == "2 ч"
    assert format_hours_minutes(2.0) == "2 ч"


def test_hours_minutes_with_minutes():
    assert format_hours_minutes(1.5) == "1 ч 30 м"
    # Текущее поведение: нулевые часы не скрываются ("0 ч 30 м").
    assert format_hours_minutes(0.5) == "0 ч 30 м"


def test_hours_minutes_zero():
    assert format_hours_minutes(0) == "0 ч"


def test_hours_minutes_negative_clamped_to_zero():
    assert format_hours_minutes(-3) == "0 ч"


def test_hours_minutes_rounds_to_nearest_minute():
    # 0.999 * 60 = 59.94 -> 60 минут -> "1 ч"
    assert format_hours_minutes(0.999) == "1 ч"


def test_hours_minutes_garbage_is_none():
    assert format_hours_minutes("abc") is None


def test_duration_compact_zero():
    assert format_duration_compact(0) == "0 ч"


def test_duration_compact_minutes_only():
    # Текущее поведение: нулевые часы не скрываются ("0 ч 45 м").
    assert format_duration_compact(60 * 45) == "0 ч 45 м"


def test_duration_compact_hours_and_minutes():
    assert format_duration_compact(3600 + 61) == "1 ч 1 м"


def test_duration_compact_drops_seconds():
    # 59 секунд — меньше минуты, округление вниз.
    assert format_duration_compact(59) == "0 ч"


def test_duration_compact_negative_clamped():
    assert format_duration_compact(-10) == "0 ч"
