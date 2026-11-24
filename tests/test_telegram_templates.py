"""Тесты чистых функций telegram.templates.

Запуск:
    .venv\\Scripts\\python.exe -m pytest tests/test_telegram_templates.py -q
"""
import pytest

from telegram.templates import (
    CAPTION_MAX_LENGTH,
    ELLIPSIS,
    FINISHED_TITLE,
    MESSAGE_MAX_LENGTH,
    VOD_LINK_LABEL,
    build_finished_entities,
    build_finished_text,
    fit_entities,
    fit_to_media_limit,
    is_own_edit,
    media_text_limit,
    normalize_vod_urls,
)
from telegram.entities import utf16_length


VOD_1 = "https://twitch.tv/videos/111111111"
VOD_2 = "https://twitch.tv/videos/222222222"
VOD_3 = "https://twitch.tv/videos/333333333"


def test_filters_blanks_and_keeps_order():
    assert normalize_vod_urls([VOD_2, "", None, "   ", f"  {VOD_1}  "]) == [
        VOD_2,
        VOD_1,
    ]


def test_removes_duplicates_preserving_order():
    assert normalize_vod_urls([VOD_2, VOD_1, VOD_2]) == [VOD_2, VOD_1]


def test_normalize_empty():
    assert normalize_vod_urls([]) == []
    assert normalize_vod_urls(None) == []


def test_single_vod():
    # Вид как у стримера: заголовок, пустая строка, подпись ссылки.
    # URL в тексте нет — ссылка отображается как 💬TWITCH~.
    assert build_finished_text([VOD_1]) == "Запись стрима:\n\n🎥TWITCH~"


def test_two_vods_are_on_separate_lines():
    assert (
        build_finished_text([VOD_1, VOD_2])
        == "Запись стрима:\n\n🎥TWITCH~\n🎥TWITCH~"
    )


def test_order_follows_argument_order():
    # Порядок задаётся вызывающим кодом по stream_started_at. Подписи
    # одинаковые, поэтому порядок виден только в HTML-версии.
    assert build_finished_text([VOD_3, VOD_1]) == build_finished_text([VOD_1, VOD_3])


def test_duplicate_vod_collapses_to_single_template():
    assert build_finished_text([VOD_1, VOD_1]) == "Запись стрима:\n\n🎥TWITCH~"


def test_finished_text_empty_input():
    assert build_finished_text([]) == ""
    assert build_finished_text(None) == ""


def test_whitespace_is_trimmed():
    assert (
        build_finished_text([f"  {VOD_1} "]) == "Запись стрима:\n\n🎥TWITCH~"
    )


def test_text_hides_url():
    # Видимый текст совпадает с тем, что вернёт Telegram: без URL,
    # иначе is_own_edit перестал бы отличать эхо правки от ручной.
    assert "twitch.tv/videos" not in build_finished_text([VOD_1])


def test_single_vod_text_has_no_url():
    # URL в тексте не видно: он лежит в entity. Так выглядит анонс
    # стримера, и именно с этим текстом сверяется is_own_edit.
    text, _entities = build_finished_entities([VOD_1])
    assert text == "Запись стрима:\n\n🎥TWITCH~"
    assert "twitch.tv" not in text


def test_link_entity_covers_exact_label():
    text, entities = build_finished_entities([VOD_1])
    assert len(entities) == 1
    entity = entities[0]
    assert entity["type"] == "text_link"
    assert entity["url"] == VOD_1
    # Смещение и длина обязаны указывать РОВНО на подпись, иначе
    # ссылка захватит заголовок или обрежется.
    # Подпись — это "TWITCH"; перед ней в лейбле стоит emoji (2 UTF-16
    # единицы), поэтому смещение считаем от позиции слова в тексте.
    assert entity["offset"] == utf16_length(text[: text.index("TWITCH")])
    assert entity["length"] == utf16_length("TWITCH")


def test_entity_offsets_use_utf16_units():
    # 💬 выше BMP: 1 кодовая точка, но 2 кодовые единицы UTF-16. Если
    # считать в точках Python, вторая ссылка уехала бы на 1 и Telegram
    # показал бы мусор вместо подписи.
    text, entities = build_finished_entities([VOD_1, VOD_2])
    second = [e for e in entities if e["url"] == VOD_2][0]
    expected = utf16_length(text[: text.rindex("TWITCH")])
    assert second["offset"] == expected


def test_each_vod_gets_only_one_link():
    _text, entities = build_finished_entities([VOD_1, VOD_2])
    assert [
        e["url"] for e in entities if e["type"] == "text_link"
    ] == [VOD_1, VOD_2]


def test_entities_empty_input():
    assert build_finished_entities([]) == ("", [])
    assert build_finished_entities(None) == ("", [])


@pytest.mark.parametrize(
    "urls",
    [[VOD_1], [VOD_1, VOD_2], [VOD_2, VOD_1]],
    ids=["single", "two", "reversed"],
)
def test_text_matches_plain_builder(urls):
    # Оба пути обязаны давать одинаковый видимый текст, иначе
    # is_own_edit перестанет узнавать эхо собственной правки.
    text, _entities = build_finished_entities(urls)
    assert text == build_finished_text(urls)


def test_is_own_edit_identical_text():
    assert is_own_edit(
        "Стрим окончен. Запись https://twitch.tv/videos/1",
        "Стрим окончен. Запись https://twitch.tv/videos/1",
    )


def test_whitespace_differences_are_ignored():
    assert is_own_edit(
        "Стрим  окончен.\nЗапись https://twitch.tv/videos/1",
        "Стрим окончен. Запись https://twitch.tv/videos/1",
    )


def test_prefix_relation_covers_truncation():
    # Бот отправил обрезанный по лимиту текст, Telegram вернул другой кусок.
    assert is_own_edit(
        "Стрим окончен. Записи:\nhttps://a",
        "Стрим окончен. Записи:\nhttps://a\nhttps://b",
    )


def test_foreign_text_is_not_own():
    assert not is_own_edit(
        "Стрим отменён из-за технических работ",
        "Стрим окончен. Запись https://twitch.tv/videos/1",
    )


def test_empty_edited_text_is_not_own():
    assert not is_own_edit("что-то", None)
    assert not is_own_edit("что-то", "")


def test_empty_incoming_is_not_own():
    # Пустой пост означает, что текст удалили вручную: бот обязан отступить.
    assert not is_own_edit("", "Стрим окончен. Запись https://twitch.tv/videos/1")
    assert not is_own_edit(None, "Стрим окончен. Запись https://twitch.tv/videos/1")


def test_limit_depends_on_media_kind():
    assert media_text_limit("photo") == CAPTION_MAX_LENGTH
    assert media_text_limit("video") == CAPTION_MAX_LENGTH
    assert media_text_limit(None) == MESSAGE_MAX_LENGTH
    assert media_text_limit("") == MESSAGE_MAX_LENGTH


def test_short_text_untouched():
    text = "Стрим онлайн"
    assert fit_to_media_limit(text, "photo") == text


def test_exact_limit_untouched():
    text = "x" * CAPTION_MAX_LENGTH
    assert fit_to_media_limit(text, "photo") == text


def test_caption_truncated():
    text = "y" * (CAPTION_MAX_LENGTH + 10)
    fitted = fit_to_media_limit(text, "photo")
    assert utf16_length(fitted) == CAPTION_MAX_LENGTH
    assert fitted.endswith(ELLIPSIS)


def test_message_limit_is_larger():
    text = "y" * (CAPTION_MAX_LENGTH + 10)
    assert fit_to_media_limit(text, None) == text


def test_long_message_truncated_at_message_limit():
    text = "y" * (MESSAGE_MAX_LENGTH + 10)
    fitted = fit_to_media_limit(text, None)
    assert utf16_length(fitted) == MESSAGE_MAX_LENGTH
    assert fitted.endswith(ELLIPSIS)


def test_limit_is_measured_in_utf16_units():
    # Регрессия: 💬 — одна кодовая точка, но две единицы UTF-16. Считая
    # длину в точках, бот отдавал бы Telegram подпись длиннее лимита
    # и получал бы отказ вместо правки.
    text = "💬" * (CAPTION_MAX_LENGTH + 50)
    fitted = fit_to_media_limit(text, "photo")
    assert utf16_length(fitted) <= CAPTION_MAX_LENGTH
    assert fitted.endswith(ELLIPSIS)


def test_truncation_never_splits_surrogate_pair():
    # Срез посередине сурогатной пары дал бы невалидный символ, который
    # Telegram не примет.
    text = "💬" * (CAPTION_MAX_LENGTH + 50)
    fitted = fit_to_media_limit(text, "photo")
    assert fitted.encode("utf-16-le", "strict").decode("utf-16-le") == fitted


def test_entities_within_limit_are_kept():
    text, entities = build_finished_entities([VOD_1])
    assert fit_entities(text, entities) == entities


def test_entities_beyond_truncation_are_dropped():
    # Регрессия: сущность за границей обрезанного текста приводит к
    # «can't parse entities», и Telegram отвергает ВЕСЬ caption —
    # теряются все ссылки, а не только одна.
    text, entities = build_finished_entities(
        [f"https://twitch.tv/videos/{index}" for index in range(200)]
    )
    text = fit_to_media_limit(text, "photo")
    kept = fit_entities(text, entities)

    assert utf16_length(text) <= CAPTION_MAX_LENGTH
    assert len(kept) < len(entities)
    assert kept
    for entity in kept:
        assert entity["offset"] + entity["length"] <= utf16_length(text)


def test_links_are_dropped_together_with_their_labels():
    # Ссылок больше, чем влезает в лимит caption: лишние целые лейблы
    # должны исчезнуть вместе со своими ссылками.
    text, entities = build_finished_entities(
        [f"https://twitch.tv/videos/{index}" for index in range(200)],
        "photo",
    )
    text = fit_to_media_limit(text, "photo")
    kept = fit_entities(text, entities)

    links = [e for e in kept if e["type"] == "text_link"]
    assert links
    assert text.endswith(ELLIPSIS)


def test_overflowing_links_leave_no_partial_label():
    # Лейбл, разрезанный обрезкой, выглядел бы как «💬TWITC…» без ссылки.
    # Вместо этого подпись теряет лишние ссылки целиком.
    text, entities = build_finished_entities(
        [f"https://twitch.tv/videos/{index}" for index in range(200)],
        "photo",
    )
    assert utf16_length(text) <= CAPTION_MAX_LENGTH
    body = text.replace(f"\n{ELLIPSIS}", "")
    for line in body.split("\n"):
        # Заголовок и пустая строка — не лейблы, их пропускаем.
        if line.strip() and line != FINISHED_TITLE:
            assert line == VOD_LINK_LABEL
