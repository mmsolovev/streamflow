"""Тесты telegram.entities: разбор эмодзи из анонса и пересчёт в UTF-16.

Запуск:
    .venv\\Scripts\\python.exe -m pytest tests/test_telegram_entities.py -q
"""
from telegram.entities import (
    build_link_entity,
    drop_entities_beyond,
    extract_link_urls,
    utf16_length,
    utf16_span,
    utf16_to_index,
)


def text_link(offset: int, length: int, url: str = "https://t.me/tabula_russia") -> dict:
    return {"type": "text_link", "offset": offset, "length": length, "url": url}


def test_ascii_length_matches_python():
    assert utf16_length("abc") == 3


def test_astral_char_counts_as_two_units():
    # Регрессия, из-за которой сдвигались все ссылки после первого эмодзи:
    # 💬 — одна кодовая точка Python, но две единицы UTF-16.
    assert len("💬") == 1
    assert utf16_length("💬") == 2


def test_mixed_text():
    assert utf16_length("ab💬cd") == 6


def test_span_after_astral_char_is_shifted():
    offset, length = utf16_span("💬ab", 1, 3)
    assert offset == 2
    assert length == 2


def test_span_of_whole_string():
    assert utf16_span("💬TWITCH~", 0, 8) == (0, 9)


def test_link_entity_shape():
    assert build_link_entity(16, 9, "https://twitch.tv/videos/1") == {
        "type": "text_link",
        "offset": 16,
        "length": 9,
        "url": "https://twitch.tv/videos/1",
    }


def test_link_entity_accepted_by_aiogram():
    # Словари из шаблона превращаются в MessageEntity на границе с API,
    # поэтому каждое поле должно быть валидным для MessageEntity.
    from aiogram.types import MessageEntity

    MessageEntity(**build_link_entity(16, 9, "https://twitch.tv/videos/1"))


def test_entities_inside_text_kept():
    entities = [build_link_entity(0, 5, "https://twitch.tv/videos/1")]
    assert drop_entities_beyond(entities, 10) == entities


def test_entity_crossing_boundary_dropped():
    # Обрезанная на границе сущность уехала бы за конец текста, и Telegram
    # отверг бы весь caption, а не одну ссылку.
    entity = build_link_entity(6, 8, "https://twitch.tv/videos/1")
    assert drop_entities_beyond([entity], 10) == []


def test_entity_starting_past_end_dropped():
    entity = build_link_entity(11, 4, "https://twitch.tv/videos/1")
    assert drop_entities_beyond([entity], 10) == []


def test_zero_length_entity_dropped():
    assert drop_entities_beyond([{"type": "url", "offset": 0, "length": 0}], 10) == []


def test_drop_empty_input():
    assert drop_entities_beyond(None, 10) == []


def test_ascii_offset():
    assert utf16_to_index("abc", 0) == 0
    assert utf16_to_index("abc", 2) == 2


def test_offset_after_astral_char():
    # 💬 занимает две кодовые единицы: смещение 2 указывает уже на 'a'.
    # Ошибка здесь сдвинула бы вырезанную ссылку на символ.
    assert utf16_to_index("💬ab", 2) == 1
    assert utf16_to_index("💬ab", 3) == 2


def test_offset_inside_surrogate_pair_lands_on_its_start():
    # Смещение 1 — это середина суррогатной пары; такое Telegram не
    # присылает, но вернуть начало символа безопаснее, чем резать по
    # кривому индексу.
    assert utf16_to_index("💬", 1) == 0


def test_offset_past_end_returns_length():
    assert utf16_to_index("abc", 99) == 3


def test_negative_offset():
    assert utf16_to_index("abc", -5) == 0


def test_hidden_channel_link():
    # Реальный случай: подпись «💬TWITCH~», адрес — только в text_link.
    caption = "Стрим онлайн! 💬TWITCH~"
    entities = [text_link(len("Стрим онлайн! 💬"), 6, "https://twitch.tv/tabula")]
    assert extract_link_urls(caption, entities) == ["https://twitch.tv/tabula"]


def test_url_entity_read_from_text():
    # У сущности типа url адрес и есть сам текст участка.
    text = "Стрим: https://twitch.tv/tabula"
    start = len("Стрим: ")
    entities = [
        {"type": "url", "offset": start, "length": len("https://twitch.tv/tabula")}
    ]
    assert extract_link_urls(text, entities) == ["https://twitch.tv/tabula"]


def test_url_entity_offset_shifted_by_emoji():
    # 💬 выше BMP: срез по сырому смещению вырезал бы мусор.
    text = "💬 twitch.tv/tabula"
    entities = [{"type": "url", "offset": 3, "length": 17}]
    assert extract_link_urls(text, entities) == ["twitch.tv/tabula"]


def test_order_preserved_and_duplicates_dropped():
    entities = [
        text_link(0, 1, "https://twitch.tv/tabula"),
        text_link(1, 1, "https://twitch.tv/videos/1"),
        text_link(2, 1, "https://twitch.tv/tabula"),
    ]
    assert extract_link_urls("abc", entities) == [
        "https://twitch.tv/tabula",
        "https://twitch.tv/videos/1",
    ]


def test_extract_no_entities():
    assert extract_link_urls("Стрим онлайн!", []) == []
    assert extract_link_urls("Стрим онлайн!", None) == []


def test_non_link_entities_ignored():
    # Форматирование не ссылки: молча пропускается.
    entities = [{"type": "bold", "offset": 0, "length": 3}]
    assert extract_link_urls("💬ab", entities) == []


def test_empty_url_dropped():
    entities = [{"type": "text_link", "offset": 0, "length": 1, "url": ""}]
    assert extract_link_urls("ab", entities) == []


def test_empty_text_yields_nothing():
    entities = [text_link(0, 1, "https://twitch.tv/tabula")]
    assert extract_link_urls("", entities) == []
    assert extract_link_urls(None, entities) == []


def test_extract_object_entities_supported():
    # aiogram отдаёт объекты MessageEntity, а не словари.
    class Entity:
        type = "text_link"
        offset = 0
        length = 6
        url = "https://twitch.tv/tabula"

    assert extract_link_urls("TWITCH", [Entity()]) == ["https://twitch.tv/tabula"]
