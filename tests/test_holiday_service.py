"""Тесты services.holiday_service: кэш праздников и выборки.

Запуск:
    .venv\\Scripts\\python.exe -m pytest tests/test_holiday_service.py -q

БД не используется: `_load_all_holidays` подменяется фейком, кэш сбрасывается.
"""
from datetime import datetime

import pytest

import services.holiday_service as holiday_service
from services.holiday_service import (
    get_all_today_names,
    get_by_index,
    get_holidays_by_date,
    get_random_today,
    get_today_key,
    invalidate_holidays_cache,
    search_holiday,
)

HOLIDAYS = {
    "01-01": [{"name": "Новый год", "desc": "Главный праздник"}],
    "09-05": [
        {"name": "День Победы", "desc": ""},
        {"name": "Парад Победы", "desc": "про парад"},
    ],
    "31-12": [{"name": "Новый год eve", "desc": ""}],
}


@pytest.fixture(autouse=True)
def fake_cache(monkeypatch):
    calls = []

    async def _fake_load():
        calls.append(1)
        return HOLIDAYS

    monkeypatch.setattr(holiday_service, "_load_all_holidays", _fake_load)
    invalidate_holidays_cache()
    yield calls
    invalidate_holidays_cache()


# --- _parse_date_key ---


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("05-04", "05-04"), ("5-4", "05-04"), ("31-12", "31-12")],
)
def test_parse_date_key_valid(raw, expected):
    assert holiday_service._parse_date_key(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "abc", "05.04", "5", "32-01", "00-00", "01-13", "1-2-3"],
)
def test_parse_date_key_invalid(raw):
    assert holiday_service._parse_date_key(raw) is None


def test_today_key_format():
    key = get_today_key()
    now = datetime.now()
    assert key == f"{now.day:02d}-{now.month:02d}"


# --- выборки ---


async def test_holidays_by_date_found():
    result = await get_holidays_by_date("09-05")
    assert len(result) == 2
    assert result[0]["name"] == "День Победы"


async def test_holidays_by_date_normalizes_key():
    assert await get_holidays_by_date("9-5") == await get_holidays_by_date("09-05")


async def test_holidays_by_date_unknown():
    assert await get_holidays_by_date("01-02") == []


async def test_holidays_by_date_invalid_key():
    assert await get_holidays_by_date("мусор") == []


async def test_random_today_returns_item_or_none(monkeypatch):
    monkeypatch.setattr(holiday_service, "get_today_key", lambda: "09-05")
    item = await get_random_today()
    assert item in HOLIDAYS["09-05"]


async def test_random_today_empty(monkeypatch):
    monkeypatch.setattr(holiday_service, "get_today_key", lambda: "01-02")
    assert await get_random_today() is None


async def test_all_today_names(monkeypatch):
    monkeypatch.setattr(holiday_service, "get_today_key", lambda: "09-05")
    assert await get_all_today_names() == ["День Победы", "Парад Победы"]


async def test_by_index():
    assert (await get_by_index("09-05", 0))["name"] == "День Победы"
    assert (await get_by_index("09-05", 1))["name"] == "Парад Победы"


@pytest.mark.parametrize("index", [-1, 2, 99])
async def test_by_index_out_of_range(index):
    assert await get_by_index("09-05", index) is None


async def test_search_case_insensitive():
    results = await search_holiday("победы")
    names = {row["name"] for row in results}
    assert names == {"День Победы", "Парад Победы"}
    assert all(row["date"] == "09-05" for row in results)


async def test_search_no_match():
    assert await search_holiday("несуществующий") == []


async def test_search_limits_to_five(monkeypatch):
    many = {
        "01-01": [{"name": f"Праздник {i}", "desc": ""} for i in range(10)]
    }

    async def _fake_load():
        return many

    monkeypatch.setattr(holiday_service, "_load_all_holidays", _fake_load)
    invalidate_holidays_cache()

    assert len(await search_holiday("Праздник")) == 5


async def test_cache_is_reused_within_ttl(fake_cache):
    await get_holidays_by_date("01-01")
    await get_holidays_by_date("09-05")
    assert len(fake_cache) == 1

    invalidate_holidays_cache()
    await get_holidays_by_date("01-01")
    assert len(fake_cache) == 2
