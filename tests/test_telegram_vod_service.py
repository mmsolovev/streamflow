"""Тесты выбора VOD по stream_id.

Запуск:
    .venv\\Scripts\\python.exe -m unittest discover -s tests -t .
"""
import unittest

from telegram.vod_service import (  # noqa: E402  (внутренние функции проверяются намеренно)
    _duration_minutes,
    _duration_seconds,
    _vod_url,
    pick_vod_for_stream,
)


class PickVodForStreamTests(unittest.TestCase):
    def _pick(self, vods, stream_id):
        """pick_vod_for_stream возвращает Optional — проверяем явно."""
        chosen = pick_vod_for_stream(vods, stream_id)
        self.assertIsNotNone(chosen)
        return chosen

    def test_exact_stream_id_match(self):
        vods = [
            {"id": "1", "stream_id": "999", "url": "https://twitch.tv/videos/1"},
            {"id": "2", "stream_id": "123456", "url": "https://twitch.tv/videos/2"},
        ]
        self.assertEqual(self._pick(vods, "123456")["id"], "2")

    def test_no_match_returns_none(self):
        vods = [{"id": "1", "stream_id": "999", "url": "https://twitch.tv/videos/1"}]
        self.assertIsNone(pick_vod_for_stream(vods, "123456"))

    def test_empty_list(self):
        self.assertIsNone(pick_vod_for_stream([], "123456"))

    def test_stream_id_compared_as_string(self):
        # Twitch отдаёт stream_id строкой, сессии тоже; int-гипотеза тут ломается.
        vods = [{"id": "1", "stream_id": "123456", "url": "https://twitch.tv/videos/1"}]
        self.assertIsNotNone(pick_vod_for_stream(vods, "123456"))

    def test_no_prefix_confusion(self):
        # stream_id 123 не должен матчить VOD потока 123456.
        vods = [{"id": "1", "stream_id": "123456", "url": "https://twitch.tv/videos/1"}]
        self.assertIsNone(pick_vod_for_stream(vods, "123"))

    def test_longest_candidate_wins(self):
        # Twitch иногда отдаёт повторную обработку; полная запись — самая длинная.
        vods = [
            {"id": "1", "stream_id": "123456", "duration": "10m0s", "url": "https://twitch.tv/videos/1"},
            {"id": "2", "stream_id": "123456", "duration": "2h0m0s", "url": "https://twitch.tv/videos/2"},
            {"id": "3", "stream_id": "123456", "duration": "1h0m0s", "url": "https://twitch.tv/videos/3"},
        ]
        self.assertEqual(self._pick(vods, "123456")["id"], "2")


class DurationTests(unittest.TestCase):
    def test_hours_minutes_seconds(self):
        self.assertEqual(_duration_seconds("2h3m4s"), 2 * 3600 + 3 * 60 + 4)

    def test_short_forms(self):
        self.assertEqual(_duration_seconds("45m0s"), 2700)
        self.assertEqual(_duration_seconds("1h0m0s"), 3600)

    def test_unparseable_is_zero(self):
        self.assertEqual(_duration_seconds("неизвестно"), 0)
        self.assertEqual(_duration_seconds(None), 0)

    def test_numeric_passthrough(self):
        self.assertEqual(_duration_seconds(90), 90)

    def test_minutes_rounded(self):
        self.assertEqual(_duration_minutes("1h2m30s"), 63)
        self.assertEqual(_duration_minutes("10m0s"), 10)

    def test_zero_minutes_is_none(self):
        # Нулевая длительность — это «неизвестно», а не «запись нулевой длины».
        self.assertIsNone(_duration_minutes("0s"))


class VodUrlTests(unittest.TestCase):
    def test_explicit_url_wins(self):
        self.assertEqual(
            _vod_url({"id": "1", "url": "https://www.twitch.tv/videos/1", "channel_login": "tabula"}),
            "https://www.twitch.tv/videos/1",
        )

    def test_built_from_id_and_login(self):
        self.assertEqual(
            _vod_url({"id": "1", "channel_login": "tabula"}),
            "https://www.twitch.tv/tabula/videos/1",
        )

    def test_none_without_id_or_login(self):
        self.assertIsNone(_vod_url({"channel_login": "tabula"}))
        self.assertIsNone(_vod_url({"id": "1"}))


if __name__ == "__main__":
    unittest.main()