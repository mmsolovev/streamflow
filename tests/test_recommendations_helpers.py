"""Тесты чистых хелперов services.recommendations_service.

Запуск:
    .venv\\Scripts\\python.exe -m pytest tests/test_recommendations_helpers.py -q

Асинхронная логика с БД (recommend_game и др.) здесь не проверяется —
только форматирование сообщений и нормализация.
"""
from datetime import datetime, timedelta, timezone

import pytest

import services.recommendations_service as recs
from services.recommendations_service import (
    _as_naive_utc,
    _format_add_message,
    _format_limit_suffix,
    _is_streamer_recommendation,
    _make_fake_add_result,
    _make_fake_delete_result,
    _make_result,
    _parse_igdb_score,
    build_recommendations_help_message,
    normalize_recommendation_name,
)


# --- нормализация ---


def test_normalize_user_login_lowercases():
    assert recs._normalize_user_login("  Tabula ") == "tabula"


def test_normalize_recommendation_name():
    assert normalize_recommendation_name("  Hades II! ") == "hades ii"


# --- _as_naive_utc ---


def test_as_naive_utc_none():
    assert _as_naive_utc(None) is None


def test_as_naive_utc_naive_passthrough():
    naive = datetime(2026, 1, 1, 12, 0)
    assert _as_naive_utc(naive) is naive


def test_as_naive_utc_aware_converted():
    aware = datetime(2026, 1, 1, 15, 0, tzinfo=timezone(timedelta(hours=3)))
    result = _as_naive_utc(aware)
    assert result == datetime(2026, 1, 1, 12, 0)
    assert result.tzinfo is None


# --- суффикс и справка ---


def test_doc_suffix_with_url(monkeypatch):
    monkeypatch.setattr(recs, "GAMES_SHEET_URL", "https://sheet.example")
    assert recs._doc_suffix() == " | Все в листах РЕЛИЗЫ и СОВЕТЫ: https://sheet.example"


def test_doc_suffix_without_url(monkeypatch):
    monkeypatch.setattr(recs, "GAMES_SHEET_URL", "")
    assert recs._doc_suffix() == ""


def test_help_message(monkeypatch):
    monkeypatch.setattr(recs, "GAMES_SHEET_URL", "https://sheet.example")
    message = build_recommendations_help_message()
    assert message.startswith("MrDestructoid Написать в чат: !рек")
    assert "https://sheet.example" in message


# --- стримерская рекомендация ---


def test_is_streamer_recommendation(monkeypatch):
    monkeypatch.setattr(recs, "RECOMMENDATIONS_STREAMER_LOGIN", "Tabula")
    assert _is_streamer_recommendation("tabula")
    assert _is_streamer_recommendation("TABULA")
    assert not _is_streamer_recommendation("viewer")


# --- форматирование лимитов и сообщений ---


def test_format_limit_suffix_empty():
    assert _format_limit_suffix(None) == ""
    assert _format_limit_suffix("") == ""


def test_format_limit_suffix_with_title():
    suffix = _format_limit_suffix("Hades")
    assert "«Hades»" in suffix
    assert "убрана из списка" in suffix


def test_format_add_message_new():
    message = _format_add_message("Celeste")
    assert message == "Игра «Celeste» занесена в список рекомендаций."


def test_format_add_message_existing():
    message = _format_add_message("Celeste", already_existing=True)
    assert "уже есть в списке" in message


def test_format_add_message_with_removed():
    message = _format_add_message("Celeste", removed_title="Hades")
    assert "занесена в список" in message
    assert "«Hades» убрана" in message


# --- результаты ---


def test_make_result_defaults():
    result = _make_result("voted", "ok")
    assert result.outcome == "voted"
    assert result.message == "ok"
    assert result.recommendation is None
    assert result.accepted is False


def test_make_fake_add_result(monkeypatch):
    monkeypatch.setattr(recs, "GAMES_SHEET_URL", "")
    result = _make_fake_add_result("  Hades  ")
    assert result.outcome == "created"
    assert result.accepted is True
    assert "«Hades»" in result.message


def test_make_fake_delete_result_with_query():
    result = _make_fake_delete_result(" Hades ")
    assert result.outcome == "deleted"
    assert "«Hades»" in result.message


def test_make_fake_delete_result_without_query():
    result = _make_fake_delete_result()
    assert result.message == "Последняя рекомендация удалена."


# --- парсинг IGDB-рейтинга ---


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ("", None),
        ("нет оценок", None),
        ("88", 88.0),
        ("88.5", 88.5),
        ("Рейтинг: 91.2 (IGDB)", 91.2),
    ],
)
def test_parse_igdb_score(raw, expected):
    assert _parse_igdb_score(raw) == expected
