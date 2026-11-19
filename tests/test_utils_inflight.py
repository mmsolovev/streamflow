"""Тесты utils.inflight: дедупликация параллельных вызовов и cooldown-окно.

Запуск:
    .venv\\Scripts\\python.exe -m pytest tests/test_utils_inflight.py -q
"""
import asyncio

import pytest

import utils.inflight as inflight
from utils.inflight import run_once


@pytest.fixture(autouse=True)
def _clean_state():
    inflight._inflight.clear()
    inflight._last_done.clear()
    yield
    inflight._inflight.clear()
    inflight._last_done.clear()


async def test_first_caller_executes_action():
    calls = []

    async def action():
        calls.append(1)
        return True

    assert await run_once("k", action) is True
    assert calls == [1]


async def test_concurrent_callers_share_single_run():
    started = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def action():
        calls.append(1)
        started.set()
        await release.wait()
        return True

    first = asyncio.create_task(run_once("k", action))
    await started.wait()
    second = asyncio.create_task(run_once("k", action))
    await asyncio.sleep(0)
    release.set()

    assert (await first) is True
    assert (await second) is False
    assert len(calls) == 1


async def test_shared_task_failure_does_not_propagate():
    started = asyncio.Event()
    release = asyncio.Event()

    async def action():
        started.set()
        await release.wait()
        raise RuntimeError("boom")

    first = asyncio.create_task(run_once("k", action))
    await started.wait()
    second = asyncio.create_task(run_once("k", action))
    await asyncio.sleep(0)
    release.set()

    # Инициатор получает True (он выполнил action), ожидающий — False,
    # исключение не пробрасывается.
    assert (await first) is True
    assert (await second) is False


async def test_cooldown_blocks_repeat_within_window():
    calls = []

    async def action():
        calls.append(1)
        return True

    assert await run_once("k", action, cooldown=10) is True
    assert await run_once("k", action, cooldown=10) is False
    assert len(calls) == 1


async def test_cooldown_expires():
    calls = []

    async def action():
        calls.append(1)
        return True

    assert await run_once("k", action, cooldown=0.05) is True
    await asyncio.sleep(0.06)
    assert await run_once("k", action, cooldown=0.05) is True
    assert len(calls) == 2


async def test_failed_action_is_not_recorded_in_cooldown():
    calls = []

    async def action():
        calls.append(1)
        raise RuntimeError("boom")

    assert await run_once("k", action, cooldown=10) is True
    # Ошибка не считается успешным ответом: следующий вызов снова executes.
    assert await run_once("k", action, cooldown=10) is True
    assert len(calls) == 2


async def test_falsy_result_is_not_recorded_in_cooldown():
    calls = []

    async def action():
        calls.append(1)
        return False

    assert await run_once("k", action, cooldown=10) is True
    assert await run_once("k", action, cooldown=10) is True
    assert len(calls) == 2


async def test_different_keys_are_independent():
    async def action():
        return True

    assert await run_once("a", action, cooldown=10) is True
    assert await run_once("b", action, cooldown=10) is True
    assert await run_once("a", action, cooldown=10) is False


async def test_zero_cooldown_never_blocks():
    calls = []

    async def action():
        calls.append(1)
        return True

    assert await run_once("k", action) is True
    assert await run_once("k", action) is True
    assert len(calls) == 2


async def test_inflight_entry_is_removed_after_run():
    async def action():
        return True

    await run_once("k", action)
    assert "k" not in inflight._inflight
