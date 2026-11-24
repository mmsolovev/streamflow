"""Тесты чистого ядра services.hltb_service.

Запуск:
    .venv\\Scripts\\python.exe -m pytest tests/test_hltb_service_core.py -q

Сеть и БД не используются: записи HLTB и метаданные — SimpleNamespace-фейки.
(`_canonicalize` покрыт отдельно в test_hltb_canonicalize.py.)
"""
from types import SimpleNamespace

import pytest

from services.hltb_service import (
    MIN_SIMILARITY,
    _build_hltb_patch,
    _build_message,
    _format_times,
    _pick_best_match,
    _sanitize,
    _strip_subtitle,
    _zero_to_none,
    clean_user_query,
    is_non_game_category,
    parse_hltb_id,
)


def _entry(**overrides):
    values = dict(
        game_id=1234,
        game_name="Hades",
        similarity=0.95,
        main_story=20.0,
        main_extra=30.0,
        completionist=50.0,
        all_styles=25.0,
        coop_time=0.0,
        mp_time=None,
        review_score=90,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def _meta(**overrides):
    values = dict(
        hltb_name="Hades",
        hltb_main_story=20.0,
        hltb_main_extra=0.0,
        hltb_completionist=50.0,
        hltb_all_styles=25.0,
        hltb_coop=None,
        hltb_multiplayer=None,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


# --- is_non_game_category ---


@pytest.mark.parametrize(
    "name",
    ["Just Chatting", "just chatting", "  IRL ", "Music", "Art"],
)
def test_non_game_categories(name):
    assert is_non_game_category(name)


@pytest.mark.parametrize("name", [None, ""])
def test_non_game_empty_name_is_non_game(name):
    assert is_non_game_category(name)


def test_real_game_is_not_non_game():
    assert not is_non_game_category("Hades")


# --- _sanitize / _strip_subtitle ---


def test_sanitize_removes_special_chars():
    assert _sanitize("Gears  of   War!!!") == "Gears of War"


def test_sanitize_keeps_allowed_chars():
    assert _sanitize("Don't Stop: The Story - v1.2") == "Don't Stop: The Story - v1.2"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("Gothic Remake -- Teaser", "Gothic Remake"),
        ("Game – Subtitle", "Game"),
        ("Game - Subtitle", "Game"),
        ("Game: Subtitle", "Game"),
        ("Game — Subtitle", "Game"),
    ],
)
def test_strip_subtitle(name, expected):
    assert _strip_subtitle(name) == expected


def test_strip_subtitle_without_separator():
    assert _strip_subtitle("Hades") is None


# --- _zero_to_none ---


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (0.0, None),
        (0, None),
        (1.5, 1.5),
        (3, 3),
        ("x", "x"),
    ],
)
def test_zero_to_none(value, expected):
    assert _zero_to_none(value) == expected


# --- _pick_best_match ---


def test_pick_best_match_highest_similarity():
    entries = [_entry(game_id=1, similarity=0.7), _entry(game_id=2, similarity=0.99)]
    assert _pick_best_match(entries).game_id == 2


def test_pick_best_match_below_threshold():
    entries = [_entry(similarity=MIN_SIMILARITY - 0.01)]
    assert _pick_best_match(entries) is None


def test_pick_best_match_at_threshold():
    entries = [_entry(similarity=MIN_SIMILARITY)]
    assert _pick_best_match(entries) is not None


def test_pick_best_match_empty():
    assert _pick_best_match([]) is None


# --- _build_hltb_patch ---


def test_build_hltb_patch_maps_fields():
    patch = _build_hltb_patch(_entry())
    assert patch == {
        "hltb_id": "1234",
        "hltb_name": "Hades",
        "hltb_main_story": 20.0,
        "hltb_main_extra": 30.0,
        "hltb_completionist": 50.0,
        "hltb_all_styles": 25.0,
        "hltb_coop": None,  # 0.0 -> None
        "hltb_multiplayer": None,
        "hltb_review_score": 90,
    }


# --- форматирование сообщения ---


def test_format_times_full():
    text = _format_times(_meta())
    # all_styles хранится в часах: 25.0 -> "25 ч".
    assert text.startswith("25 ч")
    assert "Сюжет: 20 ч" in text
    assert "Полное: 50 ч" in text
    # Нулевые/пустые категории не выводятся.
    assert "Сюжет+Доп:" not in text
    assert "Кооп:" not in text


def test_format_times_all_empty():
    meta = _meta(
        hltb_main_story=None,
        hltb_completionist=None,
        hltb_all_styles=None,
    )
    assert _format_times(meta) == ""


def test_build_message():
    message = _build_message("Hades", _meta())
    assert message.startswith("Прохождение Hades по HowLongToBeat: ")


def test_build_message_without_times_is_none():
    meta = _meta(
        hltb_main_story=None,
        hltb_completionist=None,
        hltb_all_styles=None,
    )
    assert _build_message("Hades", meta) is None


# --- clean_user_query ---


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Hades  ", "Hades"),
        ('"Hades"', "Hades"),
        ("«Hades»", "Hades"),
        (' «Hades» ', "Hades"),
    ],
)
def test_clean_user_query(raw, expected):
    assert clean_user_query(raw) == expected


# --- parse_hltb_id ---


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://howlongtobeat.com/game/84121", 84121),
        ("https://howlongtobeat.com/game/84121?foo=bar", 84121),
        ("HOWLONGTOBEAT.COM/game/1", 1),
        ("84121", 84121),
        ("  84121 ", 84121),
    ],
)
def test_parse_hltb_id_valid(raw, expected):
    assert parse_hltb_id(raw) == expected


@pytest.mark.parametrize("raw", ["", None, "abc", "https://howlongtobeat.com/", "game/84121"])
def test_parse_hltb_id_invalid(raw):
    assert parse_hltb_id(raw) is None
