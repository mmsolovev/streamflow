"""Тесты services.timer_service: глобальный таймер и таймер возврата Steam.

Запуск:
    .venv\\Scripts\\python.exe -m pytest tests/test_timer_service.py -q

Проверяются чистые функции (parse_time/format_time_left/build_status_message)
и жизненный цикл таймеров с фейковым ctx — без реального ожидания.
"""
import asyncio
import time

import pytest

import services.timer_service as timer_service
from services.timer_service import (
    RETURN_TIMER_SECONDS,
    build_status_message,
    format_time_left,
    parse_time,
    start_return_timer,
    start_timer,
    stop_return_timer,
    stop_timer,
)


class FakeCtx:
    def __init__(self):
        self.sent = []

    async def send(self, message):
        self.sent.append(message)


class _InstantAsyncio:
    """Замена asyncio для модуля: sleep(0) вместо реального ожидания."""

    CancelledError = asyncio.CancelledError
    create_task = staticmethod(asyncio.create_task)
    current_task = staticmethod(asyncio.current_task)

    @staticmethod
    async def sleep(_seconds):
        await asyncio.sleep(0)


@pytest.fixture(autouse=True)
async def _reset_timers():
    """Глобальное состояние модуля не должно протекать между тестами."""
    yield
    for name in ("_current", "_return"):
        timer = getattr(timer_service, name)
        if timer is not None and timer.task is not None:
            timer.task.cancel()
        setattr(timer_service, name, None)
    await asyncio.sleep(0)


def _fake_timer(end_offset: float, text: str = "x"):
    """_Timer без настоящей задачи — для чистых проверок статуса."""
    return timer_service._Timer(end=time.time() + end_offset, text=text, task=None)


# --- parse_time ---


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("10", 600),
        ("10м", 600),
        ("10мин", 600),
        ("10m", 600),
        ("10min", 600),
        ("2ч", 7200),
        ("2h", 7200),
        ("10М", 600),
        ("10Min", 600),
        ("0", 0),
    ],
)
def test_parse_time_valid(raw, expected):
    assert parse_time(raw) == expected


@pytest.mark.parametrize("raw", ["", "abc", "10с", "10sec", "м10"])
def test_parse_time_invalid(raw):
    assert parse_time(raw) is None


def test_parse_time_space_defaults_to_minutes():
    # Особенность текущего парсера: пробел разрывает токен, единица
    # измерения теряется и значение трактуется как минуты.
    assert parse_time("10 м") == 600


# --- format_time_left ---


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "0 с"),
        (-5, "0 с"),
        (59, "59 с"),
        (60, "1 м"),
        (61, "1 м 1 с"),
        (3600, "1 ч"),
        (3660, "1 ч 1 м"),
        (3661, "1 ч 1 м 1 с"),
    ],
)
def test_format_time_left(seconds, expected):
    assert format_time_left(seconds) == expected


# --- _prune / build_status_message ---


def test_prune_none():
    assert timer_service._prune(None) is None


def test_prune_keeps_active_timer():
    timer = _fake_timer(60)
    assert timer_service._prune(timer) is timer


def test_prune_drops_expired_timer():
    timer = _fake_timer(-1)
    assert timer_service._prune(timer) is None


def test_status_message_without_timers():
    assert build_status_message() == "HUH Активных таймеров нет"


def test_status_message_with_active_timer():
    timer_service._current = _fake_timer(125)
    message = build_status_message()
    assert message.startswith("⏳ Таймер: 2 м")


def test_status_message_with_both_timers():
    timer_service._current = _fake_timer(60)
    timer_service._return = _fake_timer(120)
    message = build_status_message()
    assert "Таймер:" in message
    assert "Возврат:" in message
    assert " | " in message


def test_status_message_prunes_expired():
    timer_service._current = _fake_timer(-10)
    assert build_status_message() == "HUH Активных таймеров нет"
    assert timer_service._current is None


# --- жизненный цикл таймеров ---


async def test_start_timer_announces_and_registers():
    ctx = FakeCtx()
    await start_timer(ctx, 3600, "PING")

    assert ctx.sent == ["NOTED Таймер на 1 ч запущен"]
    assert timer_service._current is not None
    assert timer_service._current.text == "PING"


async def test_start_timer_replaces_previous():
    ctx1, ctx2 = FakeCtx(), FakeCtx()
    await start_timer(ctx1, 3600, "OLD")
    first_task = timer_service._current.task

    await start_timer(ctx2, 3600, "NEW")
    await asyncio.sleep(0)

    assert first_task.cancelled()
    assert timer_service._current.text == "NEW"
    # Отменённая задача не успела ничего отправить.
    assert ctx1.sent == ["NOTED Таймер на 1 ч запущен"]


async def test_stop_timer_cancels_and_reports():
    ctx = FakeCtx()
    await start_timer(ctx, 3600, "PING")
    task = timer_service._current.task

    await stop_timer(ctx)
    await asyncio.sleep(0)

    assert task.cancelled()
    assert timer_service._current is None
    assert ctx.sent[-1] == "peepoLeave Таймер остановлен"


async def test_stop_timer_without_timers():
    ctx = FakeCtx()
    await stop_timer(ctx)
    assert ctx.sent == ["HUH Активных таймеров нет"]


async def test_stop_timer_falls_back_to_return_timer():
    ctx = FakeCtx()
    await start_return_timer(ctx)
    return_task = timer_service._return.task

    await stop_timer(ctx)
    await asyncio.sleep(0)

    assert return_task.cancelled()
    assert timer_service._return is None
    assert ctx.sent[-1] == "peepoLeave Таймер возврата остановлен"


async def test_timer_task_sends_text_twice_and_clears_state(monkeypatch):
    # Подменяем asyncio в модуле: sleep становится мгновенным, задача
    # проходит весь цикл (две отправки текста) без реального ожидания.
    monkeypatch.setattr(timer_service, "asyncio", _InstantAsyncio)

    ctx = FakeCtx()
    await start_timer(ctx, 0, "PING")
    task = timer_service._current.task
    await task

    # Текст отправляется дважды (повтор для видимости в чате).
    assert ctx.sent.count("PING") == 2
    assert timer_service._current is None


async def test_start_return_timer_announces():
    ctx = FakeCtx()
    await start_return_timer(ctx)

    assert ctx.sent == ["NOTED Таймер возврата Steam запущен (1ч 55м)"]
    assert timer_service._return is not None
    assert timer_service._return.text == "STEAM RETURN"
    assert RETURN_TIMER_SECONDS == 115 * 60


async def test_start_return_timer_twice_reports_remaining():
    ctx = FakeCtx()
    await start_return_timer(ctx)

    ctx2 = FakeCtx()
    await start_return_timer(ctx2)

    assert ctx2.sent[0].startswith("MadgeTime Таймер возврата уже запущен")
    assert "осталось" in ctx2.sent[0]


async def test_stop_return_timer():
    ctx = FakeCtx()
    await start_return_timer(ctx)
    task = timer_service._return.task

    await stop_return_timer(ctx)
    await asyncio.sleep(0)

    assert task.cancelled()
    assert timer_service._return is None
    assert ctx.sent[-1] == "MrDestructoid Таймер возврата остановлен 1984"


async def test_stop_return_timer_when_not_started():
    ctx = FakeCtx()
    await stop_return_timer(ctx)
    assert ctx.sent == ["MrDestructoid Таймер возврата не запущен"]
