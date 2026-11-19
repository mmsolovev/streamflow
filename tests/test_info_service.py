"""Тесты services.info_service: справка !инфо.

Запуск:
    .venv\\Scripts\\python.exe -m pytest tests/test_info_service.py -q

Файлы storage подменяются на tmp_path, lru_cache сбрасывается.
"""
import json

import pytest

import services.info_service as info_service
from services.info_service import (
    collect_keys,
    find_value,
    format_for_chat,
    fuzzy,
    resolve_query,
)

INFO_DATA = {
    "Стример": {
        "summary": "Mishgan играет каждый день",
        "Имя": "Миша",
    },
    "Компьютер": {
        "Видеокарта": "RTX 4070",
        "Процессор": "Ryzen 7",
    },
}

ALIASES = {"пк": "Компьютер"}


@pytest.fixture(autouse=True)
def info_files(tmp_path, monkeypatch):
    info_path = tmp_path / "info.json"
    info_path.write_text(json.dumps(INFO_DATA, ensure_ascii=False), encoding="utf-8")
    aliases_path = tmp_path / "aliases.json"
    aliases_path.write_text(json.dumps(ALIASES, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(info_service, "INFO_PATH", info_path)
    monkeypatch.setattr(info_service, "INFO_EXAMPLE_PATH", tmp_path / "example.json")
    monkeypatch.setattr(info_service, "ALIASES_PATH", aliases_path)
    info_service.load_info.cache_clear()
    info_service.load_aliases.cache_clear()
    yield tmp_path
    info_service.load_info.cache_clear()
    info_service.load_aliases.cache_clear()


# --- collect_keys / find_value / fuzzy ---


def test_collect_keys_flattens_and_lowercases():
    keys = collect_keys({"Стример": {"Имя": "x"}, "ПК": "y"})
    assert keys == ["стример", "имя", "пк"]


def test_collect_keys_non_dict():
    assert collect_keys(["a", "b"]) == []
    assert collect_keys("строка") == []


def test_find_value_exact_case_insensitive():
    key, value = find_value(INFO_DATA, "видеокарта")
    assert key == "Видеокарта"
    assert value == "RTX 4070"


def test_find_value_nested():
    key, value = find_value(INFO_DATA, "стример")
    assert key == "Стример"
    assert value["Имя"] == "Миша"


def test_find_value_missing():
    assert find_value(INFO_DATA, "несуществующее") is None


def test_fuzzy_match():
    assert fuzzy("видеокарт", ["видеокарта", "процессор"]) == "видеокарта"


def test_fuzzy_no_match():
    assert fuzzy("zzzzz", ["видеокарта"]) is None


# --- resolve_query ---


def test_resolve_exact():
    result = resolve_query("Процессор")
    assert result == ("Процессор", "Ryzen 7")


def test_resolve_via_alias():
    key, value = resolve_query("пк")
    assert key == "Компьютер"
    assert value["Видеокарта"] == "RTX 4070"


def test_resolve_fuzzy():
    key, value = resolve_query("видеокарт")
    assert key == "Видеокарта"
    assert value == "RTX 4070"


def test_resolve_no_match():
    assert resolve_query("квантовая физика") is None


def test_load_info_falls_back_to_example(tmp_path, monkeypatch):
    monkeypatch.setattr(info_service, "INFO_PATH", tmp_path / "absent.json")
    example = tmp_path / "example.json"
    example.write_text(json.dumps({"a": "b"}), encoding="utf-8")
    monkeypatch.setattr(info_service, "INFO_EXAMPLE_PATH", example)
    info_service.load_info.cache_clear()

    assert info_service.load_info() == {"a": "b"}


def test_load_aliases_missing_file(tmp_path, monkeypatch):
    monkeypatch.setattr(info_service, "ALIASES_PATH", tmp_path / "absent.json")
    info_service.load_aliases.cache_clear()

    assert info_service.load_aliases() == {}


# --- format_for_chat ---


def test_format_summary_wins():
    value = {"summary": "Коротко о стримере", "Имя": "Миша"}
    assert format_for_chat("Стример", value) == "Коротко о стримере"


def test_format_string_value():
    assert format_for_chat("Видеокарта", "RTX 4070") == "Видеокарта: RTX 4070"


def test_format_dict_without_summary_fallback():
    assert format_for_chat("ПК", {"Имя": "x"}) == "Нет информации 🤔"
