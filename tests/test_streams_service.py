"""Тесты services.streams_service: парсинг дат и форматирование ответа !стримы.

Запуск:
    .venv\\Scripts\\python.exe -m pytest tests/test_streams_service.py -q

БД не используется: `_load_streams_for_date` подменяется фейком.
"""
from datetime import datetime, timedelta

import pytest

import services.streams_service as streams_service
from services.streams_service import (
    StreamLookupResult,
    _format_datetime,
    _format_duration,
    _format_games,
    _parse_date,
    build_stream_response,
    build_streams_help_message,
)


@pytest.fixture(autouse=True)
def _fixed_env(monkeypatch):
    """Фиксируем URL таблицы и конвертацию UTC→локальное (Moscow)."""
    monkeypatch.setattr(streams_service, "GAMES_SHEET_URL", "https://sheet.example")
    # +3 часа, как Europe/Moscow — чтобы формат даты был предсказуем.
    monkeypatch.setattr(
        streams_service,
        "utc_to_tracker",
        lambda value: value + timedelta(hours=3) if value else None,
    )


# --- парсинг дат ---


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("05.04.2026", datetime(2026, 4, 5)),
        ("05.04.26", datetime(2026, 4, 5)),
        ("05/04/2026", datetime(2026, 4, 5)),
        ("05-04-2026", datetime(2026, 4, 5)),
        ("2026-04-05", datetime(2026, 4, 5)),
        ("2026/04/05", datetime(2026, 4, 5)),
        ("5 апреля", datetime(datetime.now().year, 4, 5)),
        ("5 апреля 26", datetime(2026, 4, 5)),
        ("05.04.2026  ", datetime(2026, 4, 5)),
    ],
)
def test_parse_date_valid(raw, expected):
    assert _parse_date(raw) == expected


def test_parse_date_short_form_uses_current_year():
    parsed = _parse_date("05.04")
    assert parsed == datetime(datetime.now().year, 4, 5)


@pytest.mark.parametrize("raw", ["", "   ", "abc", "99.99.9999", "5 апре", None])
def test_parse_date_invalid(raw):
    assert _parse_date(raw) is None


def test_parse_text_month_invalid_day():
    assert streams_service._parse_text_month_date("32 января") is None


# --- форматирование ---


def test_format_datetime_none():
    assert _format_datetime(None) == "н/д"


def test_format_datetime_converts_to_local():
    # В БД naive UTC 18:00 → в чате 21:00 (фиксированный +3).
    assert _format_datetime(datetime(2026, 4, 5, 18, 0)) == "05.04.2026 21:00"


def test_format_duration():
    assert _format_duration(None) == "н/д"
    assert _format_duration(90) == "1 ч 30 м"
    assert _format_duration(60) == "1 ч"


def test_format_games():
    assert _format_games(["Hades", "Celeste"]) == "Hades -> Celeste"
    assert _format_games([]) == "н/д"


def test_doc_suffix_with_url():
    assert streams_service._doc_suffix() == " | Все стримы канала https://sheet.example"


def test_doc_suffix_without_url(monkeypatch):
    monkeypatch.setattr(streams_service, "GAMES_SHEET_URL", "")
    assert streams_service._doc_suffix() == " Список стримов: ссылка не настроена"


def test_help_message():
    message = build_streams_help_message()
    assert message.startswith("Написать в чат: !стримы")
    assert "https://sheet.example" in message


# --- build_stream_response ---


def _stub_loader(monkeypatch, results):
    async def _fake(target_date):
        return results

    monkeypatch.setattr(streams_service, "_load_streams_for_date", _fake)


async def test_response_empty_query_returns_help(monkeypatch):
    _stub_loader(monkeypatch, [])
    assert await build_stream_response("  ") == build_streams_help_message()


async def test_response_unparseable_date(monkeypatch):
    _stub_loader(monkeypatch, [])
    message = await build_stream_response("не дата")
    assert message.startswith("Не могу распознать дату")
    assert "https://sheet.example" in message


async def test_response_no_streams_for_date(monkeypatch):
    _stub_loader(monkeypatch, [])
    message = await build_stream_response("05.04.2026")
    assert message.startswith("Стримов за дату 05.04.2026 не нахожу")


async def test_response_single_stream(monkeypatch):
    _stub_loader(
        monkeypatch,
        [
            StreamLookupResult(
                date=datetime(2026, 4, 5, 18, 0),
                duration_minutes=120,
                games=["Hades"],
            )
        ],
    )
    message = await build_stream_response("05.04.2026")
    assert "05.04.2026 21:00" in message
    assert "2 ч" in message
    assert "Hades" in message
    assert message.endswith("https://sheet.example")


async def test_response_multiple_streams_joined(monkeypatch):
    _stub_loader(
        monkeypatch,
        [
            StreamLookupResult(datetime(2026, 4, 5, 15, 0), 60, ["A"]),
            StreamLookupResult(datetime(2026, 4, 5, 18, 0), None, []),
        ],
    )
    message = await build_stream_response("05.04.2026")
    parts = message.split(" || ")
    assert len(parts) == 2
    assert "н/д" in parts[1]
