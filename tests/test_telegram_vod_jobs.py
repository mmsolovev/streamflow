"""Тесты vod_jobs: backoff ретраев и окно переиспользования анонса.

Проверяется чистая логика времени — она решает, когда задача будет
обработана снова, и поэтому обязана быть детерминированной.

Запуск:
    .venv\\Scripts\\python.exe -m unittest discover -s tests -t .
"""
import unittest
from datetime import datetime, timedelta, timezone

from telegram.vod_jobs import RETRY_BASE_SECONDS, RETRY_MAX_SECONDS, next_retry_at
from telegram.matcher import in_rebind_window


class NextRetryAtTests(unittest.TestCase):
    @staticmethod
    def _delay(attempts: int) -> float:
        # next_retry_at отдаёт naive UTC, поэтому и «сейчас» берём в UTC:
        # сравнение с локальным временем дало бы сдвиг в часовых пояса.
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        return (next_retry_at(attempts) - now).total_seconds()

    def test_first_attempt_uses_base_delay(self):
        # Считаем с attempts=1: первая неудача ждёт столько же, сколько база.
        self.assertAlmostEqual(self._delay(1), RETRY_BASE_SECONDS, delta=5)

    def test_delay_grows(self):
        self.assertGreater(self._delay(2), self._delay(1))
        self.assertGreater(self._delay(3), self._delay(2))

    def test_delay_capped(self):
        self.assertLessEqual(self._delay(50), RETRY_MAX_SECONDS + 5)

    def test_zero_attempts_does_not_shift_back(self):
        self.assertAlmostEqual(self._delay(0), RETRY_BASE_SECONDS, delta=5)

    def test_future_check_time(self):
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        self.assertGreater(next_retry_at(1), now)


class RebindWindowTests(unittest.TestCase):
    """Краш трансляции: новый broadcast продолжает старый анонс."""

    NEW_START = datetime(2026, 10, 1, 21, 5)

    def test_restart_within_window(self):
        previous_end = self.NEW_START - timedelta(minutes=10)
        self.assertTrue(in_rebind_window(previous_end, self.NEW_START, window_minutes=180))

    def test_restart_at_window_edge(self):
        previous_end = self.NEW_START - timedelta(minutes=180)
        self.assertTrue(in_rebind_window(previous_end, self.NEW_START, window_minutes=180))

    def test_restart_outside_window(self):
        # Стрим завершился 5 часов назад — это другой анонс, а не продолжение.
        previous_end = self.NEW_START - timedelta(hours=5)
        self.assertFalse(in_rebind_window(previous_end, self.NEW_START, window_minutes=180))

    def test_typical_crash_pattern(self):
        # Стрим упал в 21:00, перезапуск в 21:05 — обычный случай.
        self.assertTrue(
            in_rebind_window(datetime(2026, 10, 1, 21, 0), datetime(2026, 10, 1, 21, 5), 180)
        )


if __name__ == "__main__":
    unittest.main()