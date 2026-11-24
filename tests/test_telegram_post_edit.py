"""Тесты чистых функций telegram.post_edit."""

from telegram.post_edit import (
    DEFAULT_ITEM,
    DEFAULT_LINK_LABEL,
    PostEditTemplate,
    render_post,
    validate_template,
)


URL_ONE = "https://www.twitch.tv/videos/111"
URL_TWO = "https://www.twitch.tv/videos/222"


def test_default_single_vod():
    text, entities = render_post(PostEditTemplate(), [URL_ONE])

    assert text == "Запись стрима:\n\n🎥TWITCH~"
    assert len(entities) == 1
    assert entities[0]["type"] == "text_link"
    assert entities[0]["url"] == URL_ONE
    assert entities[0]["offset"] == 18
    assert entities[0]["length"] == 6


def test_multiple_vods_use_item_and_separator():
    text, entities = render_post(PostEditTemplate(), [URL_ONE, URL_TWO])

    assert text == "Запись стрима:\n\n🎥TWITCH~\n🎥TWITCH~"
    assert [entity["url"] for entity in entities] == [URL_ONE, URL_TWO]
    assert entities[1]["offset"] == 28


def test_duplicate_link_token_gets_two_entities():
    template = PostEditTemplate(item="{{link}} / {{link}}\n")
    text, entities = render_post(template, [URL_ONE])

    assert text == "Запись стрима:\n\nTWITCH / TWITCH\n"
    assert [entity["url"] for entity in entities] == [URL_ONE, URL_ONE]


def test_utf16_offsets_after_emoji():
    template = PostEditTemplate(header="🔥\n", item="🎥{{link}}", separator="\n")
    text, entities = render_post(template, [URL_ONE, URL_TWO])

    assert text == "🔥\n🎥TWITCH\n🎥TWITCH"
    assert entities[0]["offset"] == 5
    assert entities[1]["offset"] == 14


def test_empty_urls():
    assert render_post(PostEditTemplate(), []) == ("", [])


def test_unknown_token_rejected():
    template = PostEditTemplate(item="{{link}} {{title}}")
    assert any("Неизвестные токены" in error for error in validate_template(template))


def test_link_required():
    template = PostEditTemplate(item=DEFAULT_ITEM.replace("{{link}}", ""))
    assert any("{{link}}" in error for error in validate_template(template))


def test_link_label_required():
    template = PostEditTemplate(link_label="  ")
    assert any("Текст ссылки" in error for error in validate_template(template))


def test_tokens_forbidden_outside_item():
    template = PostEditTemplate(header="{{link}}\n")
    assert any("заголовке" in error for error in validate_template(template))


def test_link_label_preserved():
    template = PostEditTemplate(link_label="Смотреть")
    text, entities = render_post(template, [URL_ONE])

    assert "Смотреть" in text
    assert entities[0]["length"] == 8
