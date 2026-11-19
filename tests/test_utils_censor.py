"""Тесты utils.censor: цензура, обрезка командных префиксов, лимиты.

Запуск:
    .venv\\Scripts\\python.exe -m pytest tests/test_utils_censor.py -q

Реальный `storage/censorship/banned_words.json` не используется: путь
подменяется на tmp, кэш lru_cache сбрасывается.
"""
import json

import pytest

import utils.censor as censor
from utils.censor import (
    censor_text,
    load_banned_words,
    process_gpt_answer,
    sanitize_outgoing_message,
    sanitize_start,
)


@pytest.fixture()
def banned_words(tmp_path, monkeypatch):
    """Подменяет файл запрещённых слов и сбрасывает lru_cache."""
    path = tmp_path / "banned_words.json"
    monkeypatch.setattr(censor, "BANNED_WORDS_PATH", path)
    load_banned_words.cache_clear()

    def _set(words) -> None:
        path.write_text(json.dumps(words, ensure_ascii=False), encoding="utf-8")
        load_banned_words.cache_clear()

    yield _set
    load_banned_words.cache_clear()


def test_load_missing_file_is_empty_tuple(tmp_path, monkeypatch):
    monkeypatch.setattr(censor, "BANNED_WORDS_PATH", tmp_path / "absent.json")
    load_banned_words.cache_clear()
    assert load_banned_words() == ()
    load_banned_words.cache_clear()


def test_load_invalid_json_is_empty_tuple(banned_words, tmp_path):
    banned_words(["ok"])
    path = censor.BANNED_WORDS_PATH
    path.write_text("{not json", encoding="utf-8")
    load_banned_words.cache_clear()
    assert load_banned_words() == ()


def test_load_non_list_is_empty_tuple(banned_words):
    banned_words({"word": 1})
    assert load_banned_words() == ()


def test_load_filters_non_strings_and_normalizes(banned_words):
    banned_words(["Bad", "b@d", 42, None, "  ", "good"])
    # "Bad" и "b@d" нормализуются в одно слово, дубликат схлопывается.
    assert load_banned_words() == ("bad", "good")


def test_censor_empty_text_passthrough(banned_words):
    banned_words(["bad"])
    assert censor_text("") == ""
    assert censor_text(None) is None


def test_censor_without_words_keeps_text(banned_words):
    banned_words([])
    assert censor_text("anything goes") == "anything goes"


def test_censor_replaces_exact_word(banned_words):
    banned_words(["bad"])
    assert censor_text("this is bad!") == "this is ***!"


def test_censor_matches_leet_and_case_variants(banned_words):
    banned_words(["bad"])
    # @ -> a, D -> d: нормализация приводит токен к "bad".
    assert censor_text("b@D thing") == "*** thing"


def test_censor_matches_digits_substitution(banned_words):
    banned_words(["hell"])
    assert censor_text("h3ll yeah") == "**** yeah"


def test_censor_keeps_clean_words(banned_words):
    banned_words(["bad"])
    assert censor_text("good morning") == "good morning"


def test_censor_multiple_occurrences(banned_words):
    banned_words(["bad"])
    assert censor_text("bad bad bad") == "*** *** ***"


def test_sanitize_start_strips_banned_prefixes():
    assert sanitize_start("!!hello") == "hello"
    assert sanitize_start("//cmd") == "cmd"
    assert sanitize_start("...dots") == "dots"
    assert sanitize_start("!.mixed") == "mixed"


def test_sanitize_start_keeps_plain_text():
    assert sanitize_start("hello") == "hello"
    assert sanitize_start("") == ""


def test_sanitize_outgoing_replaces_newlines():
    assert sanitize_outgoing_message("a\nb\r\nc") == "a b\r c"


def test_sanitize_outgoing_applies_censor(banned_words):
    banned_words(["bad"])
    assert sanitize_outgoing_message("say bad") == "say ***"


def test_sanitize_outgoing_strips_command_prefix():
    assert sanitize_outgoing_message("!команда") == "команда"


def test_sanitize_outgoing_truncates_with_ellipsis():
    text = "x" * 500
    result = sanitize_outgoing_message(text, max_length=450)
    assert len(result) == 450
    assert result.endswith("...")


def test_sanitize_outgoing_empty_fallback():
    assert sanitize_outgoing_message("") == "****"
    assert sanitize_outgoing_message(None) == "****"
    assert sanitize_outgoing_message("   ") == "****"


def test_sanitize_outgoing_custom_fallback(banned_words):
    banned_words(["bad"])
    # Fallback срабатывает только когда текст пуст ПОСЛЕ всех фильтров;
    # цензура оставляет звёздочки, поэтому берём пробельный текст.
    assert sanitize_outgoing_message("   ", empty_fallback="нет") == "нет"


def test_process_gpt_answer_empty():
    assert process_gpt_answer("") == "MrDestructoid GPT временно недоступен"


def test_process_gpt_answer_truncated_to_150():
    result = process_gpt_answer("y" * 400)
    assert len(result) == 150
    assert result.endswith("...")


def test_process_gpt_answer_keeps_short_text():
    assert process_gpt_answer("Привет") == "Привет"
