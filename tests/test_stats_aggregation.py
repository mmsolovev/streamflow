from datetime import datetime
from types import SimpleNamespace

from services.stats_aggregation_service import build_target_values


def _row(**overrides):
    values = {
        "duration_minutes": 162,
        "streams_count": 1,
        "last_stream": datetime(2026, 8, 1),
        "max_viewers": 900,
        "avg_viewers": 321,
        "followers_per_hour": 4.5,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _aggregate(**overrides):
    values = {
        "duration_minutes": 0,
        "streams_count": 1,
        "last_stream": datetime(2026, 8, 10),
        "max_viewers": None,
        "weighted_viewer_sum": 0,
        "viewer_duration_minutes": 0,
        "viewer_unknown_rows": 0,
        "followers_gained": 0,
        "follower_duration_minutes": 0,
        "follower_unknown_rows": 0,
        "duration_unknown_rows": 0,
        "peak_unknown_rows": 0,
    }
    values.update(overrides)
    return values


def test_complete_detail_recomputes_everything():
    target = build_target_values(
        _row(),
        _aggregate(
            duration_minutes=430,
            last_stream=datetime(2026, 9, 3),
            max_viewers=1355,
        ),
    )
    assert target["duration_minutes"] == 430
    assert target["max_viewers"] == 1355
    assert target["streams_count"] == 1
    assert target["last_stream"] == datetime(2026, 9, 3)


def test_complete_detail_uses_duration_weighted_average_viewers():
    target = build_target_values(
        _row(avg_viewers=999, followers_per_hour=99),
        _aggregate(
            duration_minutes=120,
            weighted_viewer_sum=6000,
            viewer_duration_minutes=60,
            followers_gained=15,
            follower_duration_minutes=60,
        ),
    )
    assert target["avg_viewers"] == 100
    assert target["followers_per_hour"] == 15


def test_incomplete_detail_preserves_existing_viewer_rates():
    target = build_target_values(
        _row(avg_viewers=321, followers_per_hour=4.5),
        _aggregate(
            duration_unknown_rows=1,
            weighted_viewer_sum=6000,
            viewer_duration_minutes=60,
            followers_gained=15,
            follower_duration_minutes=60,
        ),
    )
    assert target["avg_viewers"] == 321
    assert target["followers_per_hour"] == 4.5


def test_unknown_duration_keeps_stored_value():
    # Legacy TT-строка без минут не должна обнулять историю.
    target = build_target_values(
        _row(duration_minutes=162),
        _aggregate(duration_unknown_rows=1),
    )
    assert target["duration_minutes"] == 162


def test_unknown_duration_without_stored_value_uses_known_sum():
    target = build_target_values(
        _row(duration_minutes=None),
        _aggregate(duration_minutes=90, duration_unknown_rows=2),
    )
    assert target["duration_minutes"] == 90


def test_unknown_peaks_do_not_lower_stored_max():
    target = build_target_values(
        _row(max_viewers=900),
        _aggregate(max_viewers=120, peak_unknown_rows=1),
    )
    assert target["max_viewers"] == 900


def test_unknown_peaks_raise_stored_max():
    target = build_target_values(
        _row(max_viewers=900),
        _aggregate(max_viewers=1355, peak_unknown_rows=1),
    )
    assert target["max_viewers"] == 1355


def test_unknown_peaks_without_stored_value_use_computed():
    target = build_target_values(
        _row(max_viewers=None),
        _aggregate(max_viewers=120, peak_unknown_rows=1),
    )
    assert target["max_viewers"] == 120


def test_empty_detail_resets_counts():
    target = build_target_values(
        _row(),
        _aggregate(
            duration_minutes=0,
            streams_count=0,
            last_stream=None,
            max_viewers=None,
        ),
    )
    assert target["duration_minutes"] == 0
    assert target["streams_count"] == 0
    assert target["last_stream"] is None
    assert target["max_viewers"] is None
