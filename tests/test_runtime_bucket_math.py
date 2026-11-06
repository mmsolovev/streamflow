"""Расчёт runtime-метрик: фолловеры по сэмплам и games_summary.

Проверяется чистая логика `runtime.metrics`: без БД и без коллектора.
Главное — прирост фолловеров на сегмент считается по разнице `followers_total`,
а `games_summary` получает те же значения и границы сегментов.

Запуск:
    .venv\\Scripts\\python.exe -m unittest tests.test_runtime_bucket_math -v
"""

import unittest

from runtime.metrics import (
    _follower_delta,
    _follower_points,
    _recalculate_segment_follow_metrics,
    recalculate_all_metrics,
)

START = "2026-01-01T00:00:00+00:00"
MID = "2026-01-01T00:30:00+00:00"
END = "2026-01-01T01:00:00+00:00"


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


class FollowerPointsTests(unittest.TestCase):
    def test_points_are_sorted_and_invalid_rows_skipped(self):
        points = _follower_points(
            [
                {"followers_total": 12, "sampled_at": "2026-01-01T00:20:00+00:00"},
                {"followers_total": "nope", "sampled_at": "2026-01-01T00:10:00+00:00"},
                {"followers_total": 10, "sampled_at": "not-a-date"},
                {"followers_total": 11, "sampled_at": "2026-01-01T00:00:00+00:00"},
            ]
        )

        self.assertEqual([value for _, value in points], [11, 12])

    def test_delta_uses_last_point_at_or_before_boundaries(self):
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

        self.assertEqual(delta, 3)

    def test_delta_is_none_for_empty_points_or_reversed_range(self):
        empty = _follower_delta([], _dt(START), _dt(END))
        reversed_range = _follower_delta(
            [( _dt(START), 10)],
            _dt(END),
            _dt(START),
        )

        self.assertIsNone(empty)
        self.assertIsNone(reversed_range)

    def test_missing_point_uses_first_known_value(self):
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

        self.assertEqual(delta, 0)


class SegmentFollowMetricsTests(unittest.TestCase):
    def test_followers_are_derived_from_samples_when_events_are_absent(self):
        session = _session()

        _recalculate_segment_follow_metrics(session)

        segments = session["game_segments"]
        self.assertEqual(segments[0]["followers_gained"], 3)
        self.assertEqual(segments[0]["followers_per_hour"], 6.0)
        self.assertEqual(segments[1]["followers_gained"], 2)
        self.assertEqual(segments[1]["followers_per_hour"], 4.0)

    def test_exact_follow_events_take_priority_over_samples(self):
        session = _session()
        session["metrics"]["follow_events"] = [
            {"followed_at": "2026-01-01T00:10:00+00:00"},
            {"followed_at": "2026-01-01T00:40:00+00:00"},
        ]

        _recalculate_segment_follow_metrics(session)

        segments = session["game_segments"]
        self.assertEqual(segments[0]["followers_gained"], 1)
        self.assertEqual(segments[1]["followers_gained"], 1)


class GamesSummaryTests(unittest.TestCase):
    def test_summary_contains_segment_bounds_and_follower_fallback(self):
        session = _session()

        recalculate_all_metrics(session)

        summary = {row["category_name"]: row for row in session["games_summary"]}
        self.assertEqual(set(summary), {"Game A", "Game B"})

        game_a = summary["Game A"]
        self.assertEqual(game_a["started_at"], START)
        self.assertEqual(game_a["ended_at"], MID)
        self.assertEqual(game_a["duration_minutes"], 30.0)
        self.assertEqual(game_a["avg_viewers"], 100.0)
        self.assertEqual(game_a["peak_viewers"], 100)
        self.assertEqual(game_a["followers_gained"], 3)

        game_b = summary["Game B"]
        self.assertEqual(game_b["started_at"], MID)
        self.assertEqual(game_b["ended_at"], END)
        self.assertEqual(game_b["duration_minutes"], 30.0)
        self.assertEqual(game_b["avg_viewers"], 50.0)
        self.assertEqual(game_b["peak_viewers"], 50)
        self.assertEqual(game_b["followers_gained"], 2)
        self.assertEqual(session["games_unique"], ["Game A", "Game B"])


def _dt(value: str):
    from datetime import datetime

    return datetime.fromisoformat(value)


if __name__ == "__main__":
    unittest.main()
