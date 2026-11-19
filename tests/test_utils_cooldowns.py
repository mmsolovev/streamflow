"""Тесты utils.cooldowns: канальные и пользовательские кулдауны.

Запуск:
    .venv\\Scripts\\python.exe -m pytest tests/test_utils_cooldowns.py -q

Время подменяется фейковыми часами, состояние модуля сбрасывается.
"""
from types import SimpleNamespace

import pytest

import utils.cooldowns as cooldowns
from utils.cooldowns import check_cooldown, check_user_cooldown


class _FakeTime:
    def __init__(self, now: float = 1000.0):
        self.now = now

    def monotonic(self) -> float:
        return self.now


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    clock = _FakeTime()
    monkeypatch.setattr(cooldowns, "time", clock)
    cooldowns._cooldowns.clear()
    cooldowns._channel_cooldowns.clear()
    yield clock
    cooldowns._cooldowns.clear()
    cooldowns._channel_cooldowns.clear()


def _ctx(user_id: int = 1):
    return SimpleNamespace(author=SimpleNamespace(id=user_id))


def test_first_call_passes(_clean_state):
    assert check_cooldown(_ctx(), "cmd", 10) is True


def test_second_call_within_timeout_blocked(_clean_state):
    ctx = _ctx()
    assert check_cooldown(ctx, "cmd", 10) is True
    _clean_state.now += 5
    assert check_cooldown(ctx, "cmd", 10) is False


def test_call_after_timeout_passes(_clean_state):
    ctx = _ctx()
    assert check_cooldown(ctx, "cmd", 10) is True
    _clean_state.now += 10
    assert check_cooldown(ctx, "cmd", 10) is True


def test_channel_cooldown_is_shared_between_users(_clean_state):
    # Глобальный кулдаун: один таймер на канал, не на пользователя.
    assert check_cooldown(_ctx(user_id=1), "cmd", 10) is True
    assert check_cooldown(_ctx(user_id=2), "cmd", 10) is False


def test_different_commands_are_independent(_clean_state):
    ctx = _ctx()
    assert check_cooldown(ctx, "a", 10) is True
    assert check_cooldown(ctx, "b", 10) is True


def test_user_cooldown_blocks_same_user(_clean_state):
    ctx = _ctx(user_id=7)
    assert check_user_cooldown(ctx, "cmd", 30) is True
    _clean_state.now += 29
    assert check_user_cooldown(ctx, "cmd", 30) is False


def test_user_cooldown_isolated_per_user(_clean_state):
    assert check_user_cooldown(_ctx(user_id=1), "cmd", 30) is True
    assert check_user_cooldown(_ctx(user_id=2), "cmd", 30) is True


def test_user_cooldown_passes_after_timeout(_clean_state):
    ctx = _ctx(user_id=7)
    assert check_user_cooldown(ctx, "cmd", 30) is True
    _clean_state.now += 30
    assert check_user_cooldown(ctx, "cmd", 30) is True


def test_user_cooldown_without_author_blocked(_clean_state):
    ctx = SimpleNamespace(author=None)
    assert check_user_cooldown(ctx, "cmd", 30) is False
