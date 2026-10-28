import unittest

from telegram.post_edit import (
    DEFAULT_ITEM,
    DEFAULT_LINK_LABEL,
    PostEditTemplate,
    render_post,
    validate_template,
)


URL_ONE = "https://www.twitch.tv/videos/111"
URL_TWO = "https://www.twitch.tv/videos/222"


class RenderPostTests(unittest.TestCase):
    def test_default_single_vod(self):
        text, entities = render_post(PostEditTemplate(), [URL_ONE])

        self.assertEqual(text, "Запись стрима:\n\n🎥TWITCH~")
        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0]["type"], "text_link")
        self.assertEqual(entities[0]["url"], URL_ONE)
        self.assertEqual(entities[0]["offset"], 18)
        self.assertEqual(entities[0]["length"], 6)

    def test_multiple_vods_use_item_and_separator(self):
        text, entities = render_post(PostEditTemplate(), [URL_ONE, URL_TWO])

        self.assertEqual(text, "Запись стрима:\n\n🎥TWITCH~\n🎥TWITCH~")
        self.assertEqual([entity["url"] for entity in entities], [URL_ONE, URL_TWO])
        self.assertEqual(entities[1]["offset"], 28)

    def test_duplicate_link_token_gets_two_entities(self):
        template = PostEditTemplate(item="{{link}} / {{link}}\n")
        text, entities = render_post(template, [URL_ONE])

        self.assertEqual(text, "Запись стрима:\n\nTWITCH / TWITCH\n")
        self.assertEqual([entity["url"] for entity in entities], [URL_ONE, URL_ONE])

    def test_utf16_offsets_after_emoji(self):
        template = PostEditTemplate(header="🔥\n", item="🎥{{link}}", separator="\n")
        text, entities = render_post(template, [URL_ONE, URL_TWO])

        self.assertEqual(text, "🔥\n🎥TWITCH\n🎥TWITCH")
        self.assertEqual(entities[0]["offset"], 5)
        self.assertEqual(entities[1]["offset"], 14)

    def test_empty_urls(self):
        self.assertEqual(render_post(PostEditTemplate(), []), ("", []))

    def test_unknown_token_rejected(self):
        template = PostEditTemplate(item="{{link}} {{title}}")
        self.assertTrue(any("Неизвестные токены" in error for error in validate_template(template)))

    def test_link_required(self):
        template = PostEditTemplate(item=DEFAULT_ITEM.replace("{{link}}", ""))
        self.assertTrue(any("{{link}}" in error for error in validate_template(template)))

    def test_link_label_required(self):
        template = PostEditTemplate(link_label="  ")
        self.assertTrue(any("Текст ссылки" in error for error in validate_template(template)))

    def test_tokens_forbidden_outside_item(self):
        template = PostEditTemplate(header="{{link}}\n")
        self.assertTrue(any("заголовке" in error for error in validate_template(template)))

    def test_link_label_preserved(self):
        template = PostEditTemplate(link_label="Смотреть")
        text, entities = render_post(template, [URL_ONE])

        self.assertIn("Смотреть", text)
        self.assertEqual(entities[0]["length"], 8)


if __name__ == "__main__":
    unittest.main()
