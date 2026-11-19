"""Тесты канонизации названий в services.hltb_service.

Запуск:
    .venv\\Scripts\\python.exe -m pytest tests/test_hltb_canonicalize.py -q
"""
from services.hltb_service import _canonicalize


def test_number_words_match_digits():
    assert _canonicalize("UNRAVEL 2") == _canonicalize("Unravel Two")


def test_number_words_to_digits():
    assert _canonicalize("It Takes Two") == "it takes 2"
    assert _canonicalize("unravel two") == "unravel 2"


def test_roman_numerals():
    assert _canonicalize("Dark Souls III") == "dark souls 3"
    assert _canonicalize("DOOM II") == "doom 2"


def test_punctuation_and_case():
    assert _canonicalize("  Gears of War!  ") == "gears of war"


def test_empty_values():
    assert _canonicalize(None) == ""
    assert _canonicalize("") == ""
