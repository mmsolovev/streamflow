"""Тесты utils.delays: человеческие задержки без реального сна.

Запуск:
    .venv\\Scripts\\python.exe -m pytest tests/test_utils_delays.py -q
"""
import pytest

import utils.delays as delays
from utils.delays import custom_delay, human_delay


class _FakeAsyncio:
    """Записывает запросы на sleep вместо настоящего ожидания."""

    def __init__(self):
        self.slept = []

    async def sleep(self, seconds):
        self.slept.append(seconds)


@pytest.fixture()
def fake_asyncio(monkeypatch):
    fake = _FakeAsyncio()
    monkeypatch.setattr(delays, "asyncio", fake)
    return fake


async def test_human_delay_in_default_range(fake_asyncio):
    result = await human_delay()
    assert 2.3 <= result <= 4.1
    assert fake_asyncio.slept == [result]


async def test_custom_delay_scales_by_multiplier(fake_asyncio):
    result = await custom_delay(2, min_delay=1, max_delay=2)
    assert 2.0 <= result <= 4.0
    assert fake_asyncio.slept == [result]


async def test_custom_delay_respects_bounds(fake_asyncio):
    result = await custom_delay(1, min_delay=5, max_delay=5)
    assert result == 5.0


async def test_swapped_bounds_are_normalized(fake_asyncio):
    # Границы переданы в обратном порядке — функция их меняет местами.
    result = await custom_delay(1, min_delay=9, max_delay=3)
    assert 3.0 <= result <= 9.0


async def test_returns_actual_delay_for_logging(fake_asyncio):
    result = await custom_delay(0.5, min_delay=2, max_delay=4)
    assert 1.0 <= result <= 2.0
    assert isinstance(result, float)
