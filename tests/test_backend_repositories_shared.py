"""Tests for web repository shared helpers (pure functions)."""
import unittest
from datetime import datetime, timedelta

from backend.repositories._shared import (
    build_recommenders_text,
    build_tags_text,
    format_duration_hours,
    release_delta_days,
)


class SharedHelperTests(unittest.TestCase):
    def test_build_tags_text_joins_parts(self):
        self.assertEqual(build_tags_text("PC", "Action"), "PC | Action")
        self.assertEqual(build_tags_text("PC", ""), "PC")
        self.assertEqual(build_tags_text(None, None), "")

    def test_build_recommenders_text_special_users(self):
        data = [
            {"user_login": "tabula", "display_name": "Tabula"},
            {"user_login": "igdb", "display_name": "IGDB"},
            {"user_login": "someone", "display_name": "Someone"},
        ]
        self.assertEqual(build_recommenders_text(data), "В желаемом, Хайп, Someone")

    def test_build_recommenders_text_empty(self):
        self.assertEqual(build_recommenders_text([]), "")
        self.assertEqual(build_recommenders_text(None), "")

    def test_release_delta_days(self):
        self.assertIsNone(release_delta_days(None))
        future = datetime.utcnow() + timedelta(days=5)
        self.assertEqual(release_delta_days(future), 5)
        past = datetime.utcnow() - timedelta(days=1)
        self.assertIsNone(release_delta_days(past))

    def test_format_duration_hours(self):
        self.assertEqual(format_duration_hours(None), 0.0)
        self.assertEqual(format_duration_hours(0), 0.0)
        self.assertEqual(format_duration_hours(90), 1.5)


if __name__ == "__main__":
    unittest.main()