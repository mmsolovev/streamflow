"""Тесты services.reply_layout_service: перевод раскладки и дедупликация ответов.

Запуск:
    .venv\\Scripts\\python.exe -m pytest tests/test_reply_layout_service.py -q
"""
from types import SimpleNamespace

import pytest

import services.reply_layout_service as rls
from services.reply_layout_service import (
    MAX_MESSAGE_LENGTH,
    build_reply_translation_response,
    claim_reply_translation,
    extract_reply_message_data,
    translate_keyboard_layout,
)


@pytest.fixture(autouse=True)
def _reset_processed(monkeypatch):
    rls._processed_reply_ids.clear()
    yield
    rls._processed_reply_ids.clear()


# --- перевод раскладки ---


def test_english_typed_as_russian_is_translated():
    # «ghbdtn» — «привет», набранное в английской раскладке.
    assert translate_keyboard_layout("ghbdtn") == "привет"


def test_russian_typed_as_english_is_translated():
    # «rfr ltkf» — «как дела» в английской раскладке.
    assert translate_keyboard_layout("rfr ltkf") == "как дела"


def test_natural_english_stays():
    assert translate_keyboard_layout("hello world") == "hello world"


def test_natural_russian_stays():
    assert translate_keyboard_layout("привет мир") == "привет мир"


def test_short_text_prefers_natural_variant():
    # Мало букв — эвристики «естественности» не хватает, выбор по счёту.
    result = translate_keyboard_layout("ok")
    assert isinstance(result, str) and result


def test_counts():
    assert rls._count_latin("aBc 123") == 3
    assert rls._count_cyrillic("аБв 123") == 3
    assert rls._count_cyrillic("ёжик") == 4


def test_vowel_ratio():
    assert rls._vowel_ratio("ау") == 1.0
    assert rls._vowel_ratio("бв") == 0.0
    assert rls._vowel_ratio("123") == 0.0


# --- обрезка ответа ---


def test_truncate_short_text():
    result = rls._truncate_response("Tabula", "привет")
    assert result == "Написано: Tabula: привет"


def test_truncate_long_text():
    result = rls._truncate_response("Tabula", "x" * 1000)
    assert len(result) <= MAX_MESSAGE_LENGTH
    assert result.endswith("...")
    assert result.startswith("Написано: Tabula: ")


def test_build_response_translates_body():
    result = build_reply_translation_response("Tabula", "  ghbdtn  ")
    assert result == "Написано: Tabula: привет"


# --- извлечение данных reply ---


def test_extract_reply_without_reply():
    message = SimpleNamespace(reply=None)
    assert extract_reply_message_data(message) == (None, None, None)


def test_extract_reply_full():
    message = SimpleNamespace(
        reply=SimpleNamespace(
            parent_message_id="m1",
            parent_user=SimpleNamespace(display_name="Tabula"),
            parent_message_body="текст",
        )
    )
    assert extract_reply_message_data(message) == ("m1", "Tabula", "текст")


@pytest.mark.parametrize(
    "reply",
    [
        SimpleNamespace(
            parent_message_id=None,
            parent_user=SimpleNamespace(display_name="Tabula"),
            parent_message_body="текст",
        ),
        SimpleNamespace(
            parent_message_id="m1",
            parent_user=None,
            parent_message_body="текст",
        ),
        SimpleNamespace(
            parent_message_id="m1",
            parent_user=SimpleNamespace(display_name="Tabula"),
            parent_message_body=None,
        ),
    ],
)
def test_extract_reply_incomplete(reply):
    assert extract_reply_message_data(SimpleNamespace(reply=reply)) == (
        None,
        None,
        None,
    )


# --- дедупликация переводов ---


async def test_claim_reply_first_time_true():
    assert await claim_reply_translation("m1") is True


async def test_claim_reply_second_time_false():
    assert await claim_reply_translation("m1") is True
    assert await claim_reply_translation("m1") is False


async def test_claim_reply_different_ids():
    assert await claim_reply_translation("m1") is True
    assert await claim_reply_translation("m2") is True


async def test_claim_reply_expires(monkeypatch):
    clock = {"now": 1000.0}
    monkeypatch.setattr(rls.time, "time", lambda: clock["now"])

    assert await claim_reply_translation("m1") is True
    assert await claim_reply_translation("m1") is False

    clock["now"] += rls.MAX_REPLY_CACHE_SECONDS + 1
    assert await claim_reply_translation("m1") is True
