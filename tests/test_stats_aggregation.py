import unittest
from datetime import datetime
from types import SimpleNamespace

from services.stats_aggregation_service import build_target_values


def _row(**overrides):
    values = {
        "duration_minutes": 162,
        "streams_count": 1,
        "last_stream": datetime(2026, 8, 1),
        "max_viewers": 900,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _aggregate(**overrides):
    values = {
        "duration_minutes": 0,
        "streams_count": 1,
        "last_stream": datetime(2026, 8, 10),
        "max_viewers": None,
        "duration_unknown_rows": 0,
        "peak_unknown_rows": 0,
    }
    values.update(overrides)
    return values


class BuildTargetValuesTests(unittest.TestCase):
    def test_complete_detail_recomputes_everything(self):
        target = build_target_values(
            _row(),
            _aggregate(
                duration_minutes=430,
                last_stream=datetime(2026, 9, 3),
                max_viewers=1355,
            ),
        )
        self.assertEqual(target["duration_minutes"], 430)
        self.assertEqual(target["max_viewers"], 1355)
        self.assertEqual(target["streams_count"], 1)
        self.assertEqual(target["last_stream"], datetime(2026, 9, 3))

    def test_unknown_duration_keeps_stored_value(self):
        # Legacy TT-строка без минут не должна обнулять историю.
        target = build_target_values(
            _row(duration_minutes=162),
            _aggregate(duration_unknown_rows=1),
        )
        self.assertEqual(target["duration_minutes"], 162)

    def test_unknown_duration_without_stored_value_uses_known_sum(self):
        target = build_target_values(
            _row(duration_minutes=None),
            _aggregate(duration_minutes=90, duration_unknown_rows=2),
        )
        self.assertEqual(target["duration_minutes"], 90)

    def test_unknown_peaks_do_not_lower_stored_max(self):
        target = build_target_values(
            _row(max_viewers=900),
            _aggregate(max_viewers=120, peak_unknown_rows=1),
        )
        self.assertEqual(target["max_viewers"], 900)

    def test_unknown_peaks_raise_stored_max(self):
        target = build_target_values(
            _row(max_viewers=900),
            _aggregate(max_viewers=1355, peak_unknown_rows=1),
        )
        self.assertEqual(target["max_viewers"], 1355)

    def test_unknown_peaks_without_stored_value_use_computed(self):
        target = build_target_values(
            _row(max_viewers=None),
            _aggregate(max_viewers=120, peak_unknown_rows=1),
        )
        self.assertEqual(target["max_viewers"], 120)

    def test_empty_detail_resets_counts(self):
        target = build_target_values(
            _row(),
            _aggregate(
                duration_minutes=0,
                streams_count=0,
                last_stream=None,
                max_viewers=None,
            ),
        )
        self.assertEqual(target["duration_minutes"], 0)
        self.assertEqual(target["streams_count"], 0)
        self.assertIsNone(target["last_stream"])
        self.assertIsNone(target["max_viewers"])


if __name__ == "__main__":
    unittest.main()
