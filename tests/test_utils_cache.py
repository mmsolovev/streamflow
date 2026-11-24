"""Тесты utils.cache: JSON-кэш в storage/cache.

Запуск:
    .venv\\Scripts\\python.exe -m pytest tests/test_utils_cache.py -q

Каталог кэша подменяется на tmp_path — реальный storage/cache не трогается.
"""
import pytest

import utils.cache as cache
from utils.cache import load_cache, save_cache


@pytest.fixture(autouse=True)
def cache_dir(tmp_path, monkeypatch):
    directory = tmp_path / "cache"
    monkeypatch.setattr(cache, "CACHE_DIR", str(directory))
    return directory


def test_load_missing_file_returns_empty_dict(cache_dir):
    cache_dir.mkdir(parents=True, exist_ok=True)
    assert load_cache("absent") == {}


def test_load_creates_directory(cache_dir):
    assert not cache_dir.exists()
    assert load_cache("x") == {}
    assert cache_dir.exists()


def test_load_empty_file_returns_empty_dict(cache_dir):
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "empty.json").write_text("", encoding="utf-8")
    assert load_cache("empty") == {}


def test_load_invalid_json_returns_empty_dict(cache_dir):
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "broken.json").write_text("{oops", encoding="utf-8")
    assert load_cache("broken") == {}


def test_save_then_load_roundtrip(cache_dir):
    load_cache("init")  # гарантирует существование каталога
    data = {"игры": ["Hades", "Celeste"], "count": 2}
    save_cache("games", data)
    assert load_cache("games") == data


def test_save_writes_unicode_unescaped(cache_dir):
    load_cache("init")
    save_cache("uni", {"слово": "значение"})
    raw = (cache_dir / "uni.json").read_text(encoding="utf-8")
    assert "значение" in raw


def test_save_overwrites_previous(cache_dir):
    load_cache("init")
    save_cache("k", {"a": 1})
    save_cache("k", {"b": 2})
    assert load_cache("k") == {"b": 2}
