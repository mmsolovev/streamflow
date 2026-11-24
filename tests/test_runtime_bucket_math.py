"""Расчёт runtime-метрик: фолловеры по сэмплам и games_summary.

Проверяется чистая логика `runtime.metrics`: без БД и без коллектора.
Главное — прирост фолловеров на сегмент считается по разнице `followers_total`,
а `games_summary` получает те же значения и границы сегментов.

Запуск:
    .venv\\Scripts\\python.exe -m pytest tests/test_runtime_bucket_math.py -q
"""

from datetime import datetime, timedelta

from runtime.metrics import (
    _follower_delta,
    _follower_points,
    _recalculate_segment_follow_metrics,
    recalculate_all_metrics,
)

START = "2026-01-01T00:00:00+00:00"
MID = "2026-01-01T00:30:00+00:00"
END = "2026-01-01T01:00:00+00:00"


def _dt(value: str):
    return datetime.fromisoformat(value)


def _session() -> dict:
    return {
        "status": "completed",
        "started_at": START,
        "ended_at": END,
        "game_segments": [
            {
                "category_id": "1",
                "category_name": "Game A",
                "started_at": START,
                "ended_at": MID,
                "source": "sampling.loop",
            },
            {
                "category_id": "2",
                "category_name": "Game B",
                "started_at": MID,
                "ended_at": END,
                "source": "sampling.loop",
            },
        ],
        "metrics": {
            "viewer_samples": [
                {"viewer_count": 100, "sampled_at": "2026-01-01T00:05:00+00:00"},
                {"viewer_count": 100, "sampled_at": "2026-01-01T00:10:00+00:00"},
                {"viewer_count": 100, "sampled_at": "2026-01-01T00:20:00+00:00"},
                {"viewer_count": 50, "sampled_at": "2026-01-01T00:40:00+00:00"},
                {"viewer_count": 50, "sampled_at": "2026-01-01T00:50:00+00:00"},
            ],
            "follower_samples": [
                {"followers_total": 10, "sampled_at": "2026-01-01T00:00:00+00:00"},
                {"followers_total": 12, "sampled_at": "2026-01-01T00:20:00+00:00"},
                {"followers_total": 13, "sampled_at": "2026-01-01T00:30:00+00:00"},
                {"followers_total": 15, "sampled_at": "2026-01-01T01:00:00+00:00"},
            ],
            "follow_events": [],
        },
    }


def test_points_are_sorted_and_invalid_rows_skipped():
    points = _follower_points(
        [
            {"followers_total": 12, "sampled_at": "2026-01-01T00:20:00+00:00"},
            {"followers_total": "nope", "sampled_at": "2026-01-01T00:10:00+00:00"},
            {"followers_total": 10, "sampled_at": "not-a-date"},
            {"followers_total": 11, "sampled_at": "2026-01-01T00:00:00+00:00"},
        ]
    )

    assert [value for _, value in points] == [11, 12]


def test_delta_uses_last_point_at_or_before_boundaries():
    points = _follower_points(
        [
            {"followers_total": 10, "sampled_at": "2026-01-01T00:00:00+00:00"},
            {"followers_total": 12, "sampled_at": "2026-01-01T00:20:00+00:00"},
            {"followers_total": 13, "sampled_at": "2026-01-01T00:30:00+00:00"},
        ]
    )

    delta = _follower_delta(
        points,
        _dt("2026-01-01T00:00:00+00:00"),
        _dt("2026-01-01T00:30:00+00:00"),
    )

    assert delta == 3


def test_delta_is_none_for_empty_points_or_reversed_range():
    empty = _follower_delta([], _dt(START), _dt(END))
    reversed_range = _follower_delta(
        [(_dt(START), 10)],
        _dt(END),
        _dt(START),
    )

    assert empty is None
    assert reversed_range is None


def test_missing_point_uses_first_known_value():
    points = _follower_points(
        [
            {"followers_total": 5, "sampled_at": "2026-01-01T00:10:00+00:00"},
            {"followers_total": 7, "sampled_at": "2026-01-01T00:20:00+00:00"},
        ]
    )

    delta = _follower_delta(
        points,
        _dt("2026-01-01T00:00:00+00:00"),
        _dt("2026-01-01T00:15:00+00:00"),
    )

    assert delta == 0


def test_followers_are_derived_from_samples_when_events_are_absent():
    session = _session()

    _recalculate_segment_follow_metrics(session)

    segments = session["game_segments"]
    assert segments[0]["followers_gained"] == 3
    assert segments[0]["followers_per_hour"] == 6.0
    assert segments[1]["followers_gained"] == 2
    assert segments[1]["followers_per_hour"] == 4.0


def test_exact_follow_events_take_priority_over_samples():
    session = _session()
    session["metrics"]["follow_events"] = [
        {"followed_at": "2026-01-01T00:10:00+00:00"},
        {"followed_at": "2026-01-01T00:40:00+00:00"},
    ]

    _recalculate_segment_follow_metrics(session)

    segments = session["game_segments"]
    assert segments[0]["followers_gained"] == 1
    assert segments[1]["followers_gained"] == 1


def test_summary_contains_segment_bounds_and_follower_fallback():
    session = _session()

    recalculate_all_metrics(session)

    summary = {row["category_name"]: row for row in session["games_summary"]}
    assert set(summary) == {"Game A", "Game B"}

    game_a = summary["Game A"]
    assert game_a["started_at"] == START
    assert game_a["ended_at"] == MID
    assert game_a["duration_minutes"] == 30.0
    assert game_a["avg_viewers"] == 100.0
    assert game_a["peak_viewers"] == 100
    assert game_a["followers_gained"] == 3

    game_b = summary["Game B"]
    assert game_b["started_at"] == MID
    assert game_b["ended_at"] == END
    assert game_b["duration_minutes"] == 30.0
    assert game_b["avg_viewers"] == 50.0
    assert game_b["peak_viewers"] == 50
    assert game_b["followers_gained"] == 2
    assert session["games_unique"] == ["Game A", "Game B"]


def test_summary_ignores_games_under_ten_minutes_but_keeps_exact_threshold_and_summed_visits():
    start = _dt(START)
    short_end = start + timedelta(seconds=599)
    ten_min_end = short_end + timedelta(seconds=600)
    split_first_end = ten_min_end + timedelta(seconds=300)
    split_second_start = split_first_end + timedelta(seconds=60)
    end = split_second_start + timedelta(seconds=300)

    session = {
        "status": "completed",
        "started_at": _iso(start),
        "ended_at": _iso(end),
        "game_segments": [
            {
                "category_id": "short",
                "category_name": "Wrong category",
                "started_at": _iso(start),
                "ended_at": _iso(short_end),
            },
            {
                "category_id": "threshold",
                "category_name": "Ten minutes",
                "started_at": _iso(short_end),
                "ended_at": _iso(ten_min_end),
            },
            {
                "category_id": "split",
                "category_name": "Played twice",
                "started_at": _iso(ten_min_end),
                "ended_at": _iso(split_first_end),
            },
            {
                "category_id": "other",
                "category_name": "Intervening game",
                "started_at": _iso(split_first_end),
                "ended_at": _iso(split_second_start),
            },
            {
                "category_id": "split",
                "category_name": "Played twice",
                "started_at": _iso(split_second_start),
                "ended_at": _iso(end),
            },
        ],
        "metrics": {
            "viewer_samples": [],
            "follower_samples": [],
            "follow_events": [],
        },
    }

    recalculate_all_metrics(session)

    summary = {row["category_name"]: row for row in session["games_summary"]}
    assert "Wrong category" not in summary
    assert summary["Ten minutes"]["duration_minutes"] == 10.0
    assert summary["Played twice"]["duration_minutes"] == 10.0
    assert session["games_unique"] == ["Ten minutes", "Played twice"]


def _iso(value: datetime) -> str:
    return value.isoformat()
