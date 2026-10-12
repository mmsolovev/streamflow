"""Тесты telegram.entities: разбор эмодзи из анонса и пересчёт в UTF-16.

Запуск:
    .venv\\Scripts\\python.exe -m unittest discover -s tests -t .
"""
import unittest

from telegram.entities import (
    build_custom_emoji_entity,
    build_link_entity,
    drop_entities_beyond,
    extract_link_urls,
    find_custom_emoji_id,
    utf16_length,
    utf16_span,
    utf16_to_index,
)


EMOJI_ID = "5381234567"


def custom_emoji(offset: int, length: int = 2, emoji_id: str = EMOJI_ID) -> dict:
    return {"type": "custom_emoji", "offset": offset, "length": length, "custom_emoji_id": emoji_id}


def text_link(offset: int, length: int, url: str = "https://t.me/tabula_russia") -> dict:
    return {"type": "text_link", "offset": offset, "length": length, "url": url}


class Utf16Tests(unittest.TestCase):
    """Смещения entities Telegram считает в UTF-16, а не в кодовых точках."""

    def test_ascii_length_matches_python(self):
        self.assertEqual(utf16_length("abc"), 3)

    def test_astral_char_counts_as_two_units(self):
        # Регрессия, из-за которой сдвигались все ссылки после первого эмодзи:
        # 💬 — одна кодовая точка Python, но две единицы UTF-16.
        self.assertEqual(len("💬"), 1)
        self.assertEqual(utf16_length("💬"), 2)

    def test_mixed_text(self):
        self.assertEqual(utf16_length("ab💬cd"), 6)

    def test_span_after_astral_char_is_shifted(self):
        offset, length = utf16_span("💬ab", 1, 3)
        self.assertEqual(offset, 2)
        self.assertEqual(length, 2)

    def test_span_of_whole_string(self):
        self.assertEqual(utf16_span("💬TWITCH~", 0, 8), (0, 9))


class FindCustomEmojiIdTests(unittest.TestCase):
    """Эмодзи берётся из того, что стример поставил в записи о канале."""

    def test_no_entities(self):
        self.assertIsNone(find_custom_emoji_id(None))
        self.assertIsNone(find_custom_emoji_id([]))

    def test_emoji_inside_channel_link_wins(self):
        # Эмодзи внутри ссылки на канал — именно тот, что нужен для записи.
        entities = [custom_emoji(2), text_link(2, 10)]
        self.assertEqual(find_custom_emoji_id(entities), EMOJI_ID)

    def test_nearest_emoji_to_link_used(self):
        # Эмодзи стоит перед ссылкой, не внутри неё: берётся ближайший.
        entities = [custom_emoji(0), text_link(2, 10)]
        self.assertEqual(find_custom_emoji_id(entities), EMOJI_ID)

    def test_decorative_emoji_loses_to_link_one(self):
        # В посте два эмодзи: украшение в начале и нужный у самой ссылки.
        entities = [
            custom_emoji(0, emoji_id="111"),
            custom_emoji(20, emoji_id="222"),
            text_link(22, 10),
        ]
        self.assertEqual(find_custom_emoji_id(entities), "222")

    def test_single_emoji_without_any_link(self):
        # Ссылки в анонсе может не быть вовсе — эмодзи стримера всё равно
        # единственный, и подпись станет такой же, как у него.
        self.assertEqual(find_custom_emoji_id([custom_emoji(5)]), EMOJI_ID)

    def test_plain_unicode_emoji_is_not_custom(self):
        # Обычный Unicode-эмодзи не несёт custom_emoji_id: подпись соберётся
        # на самом символе, и это правильный запасной вариант.
        self.assertIsNone(find_custom_emoji_id([{"type": "emoji", "offset": 0, "length": 2}]))

    def test_custom_emoji_without_id_ignored(self):
        entities = [{"type": "custom_emoji", "offset": 0, "length": 2}]
        self.assertIsNone(find_custom_emoji_id(entities))

    def test_returns_string_not_int(self):
        # Bot API отдаёт id строкой и в entities требует строку: приведение
        # к int потеряло бы формат значения при подстановке в tg://emoji.
        self.assertIsInstance(find_custom_emoji_id([custom_emoji(0)]), str)

    def test_object_entities_supported(self):
        # aiogram отдаёт объекты MessageEntity, а не словари.
        class Entity:
            type = "custom_emoji"
            offset = 0
            length = 2
            custom_emoji_id = EMOJI_ID

        self.assertEqual(find_custom_emoji_id([Entity()]), EMOJI_ID)


class EntityBuildersTests(unittest.TestCase):
    def test_link_entity_shape(self):
        self.assertEqual(
            build_link_entity(16, 9, "https://twitch.tv/videos/1"),
            {
                "type": "text_link",
                "offset": 16,
                "length": 9,
                "url": "https://twitch.tv/videos/1",
            },
        )

    def test_custom_emoji_entity_coerces_id_to_str(self):
        # Bot API ждёт id строкой: приведение к int потеряло бы формат
        # значения при подстановке обратно в entities.
        entity = build_custom_emoji_entity(16, 2, "5381234567")
        self.assertEqual(entity["custom_emoji_id"], "5381234567")

    def test_entity_accepted_by_aiogram(self):
        # Словари из шаблона превращаются в MessageEntity на границе с API,
        # поэтому каждое поле должно быть валидным для MessageEntity.
        from aiogram.types import MessageEntity

        for entity in (
            build_link_entity(16, 9, "https://twitch.tv/videos/1"),
            build_custom_emoji_entity(16, 2, EMOJI_ID),
        ):
            with self.subTest(entity=entity["type"]):
                MessageEntity(**entity)


class DropEntitiesBeyondTests(unittest.TestCase):
    def test_entities_inside_text_kept(self):
        entities = [build_link_entity(0, 5, "https://twitch.tv/videos/1")]
        self.assertEqual(drop_entities_beyond(entities, 10), entities)

    def test_entity_crossing_boundary_dropped(self):
        # Обрезанная на границе сущность уехала бы за конец текста, и Telegram
        # отверг бы весь caption, а не одну ссылку.
        entity = build_link_entity(6, 8, "https://twitch.tv/videos/1")
        self.assertEqual(drop_entities_beyond([entity], 10), [])

    def test_entity_starting_past_end_dropped(self):
        entity = build_link_entity(11, 4, "https://twitch.tv/videos/1")
        self.assertEqual(drop_entities_beyond([entity], 10), [])

    def test_zero_length_entity_dropped(self):
        self.assertEqual(drop_entities_beyond([{"type": "url", "offset": 0, "length": 0}], 10), [])

    def test_empty_input(self):
        self.assertEqual(drop_entities_beyond(None, 10), [])


class Utf16ToIndexTests(unittest.TestCase):
    """Обратный перевод смещения Telegram в индекс Python-строки."""

    def test_ascii_offset(self):
        self.assertEqual(utf16_to_index("abc", 0), 0)
        self.assertEqual(utf16_to_index("abc", 2), 2)

    def test_offset_after_astral_char(self):
        # 💬 занимает две кодовые единицы: смещение 2 указывает уже на 'a'.
        # Ошибка здесь сдвинула бы вырезанную ссылку на символ.
        self.assertEqual(utf16_to_index("💬ab", 2), 1)
        self.assertEqual(utf16_to_index("💬ab", 3), 2)

    def test_offset_inside_surrogate_pair_lands_on_its_start(self):
        # Смещение 1 — это середина суррогатной пары; такое Telegram не
        # присылает, но вернуть начало символа безопаснее, чем резать по
        # кривому индексу.
        self.assertEqual(utf16_to_index("💬", 1), 0)

    def test_offset_past_end_returns_length(self):
        self.assertEqual(utf16_to_index("abc", 99), 3)

    def test_negative_offset(self):
        self.assertEqual(utf16_to_index("abc", -5), 0)


class ExtractLinkUrlsTests(unittest.TestCase):
    """Ссылки достаются из entities: в тексте скрытой ссылки адреса нет."""

    def test_hidden_channel_link(self):
        # Реальный случай: подпись «💬TWITCH~», адрес — только в text_link.
        caption = "Стрим онлайн! 💬TWITCH~"
        entities = [text_link(len("Стрим онлайн! 💬"), 6, "https://twitch.tv/tabula")]
        self.assertEqual(
            extract_link_urls(caption, entities),
            ["https://twitch.tv/tabula"],
        )

    def test_url_entity_read_from_text(self):
        # У сущности типа url адрес и есть сам текст участка.
        text = "Стрим: https://twitch.tv/tabula"
        start = len("Стрим: ")
        entities = [{"type": "url", "offset": start, "length": len("https://twitch.tv/tabula")}]
        self.assertEqual(extract_link_urls(text, entities), ["https://twitch.tv/tabula"])

    def test_url_entity_offset_shifted_by_emoji(self):
        # 💬 выше BMP: срез по сырому смещению вырезал бы мусор.
        text = "💬 twitch.tv/tabula"
        entities = [{"type": "url", "offset": 3, "length": 17}]
        self.assertEqual(extract_link_urls(text, entities), ["twitch.tv/tabula"])

    def test_order_preserved_and_duplicates_dropped(self):
        entities = [
            text_link(0, 1, "https://twitch.tv/tabula"),
            text_link(1, 1, "https://twitch.tv/videos/1"),
            text_link(2, 1, "https://twitch.tv/tabula"),
        ]
        self.assertEqual(
            extract_link_urls("abc", entities),
            ["https://twitch.tv/tabula", "https://twitch.tv/videos/1"],
        )

    def test_no_entities(self):
        self.assertEqual(extract_link_urls("Стрим онлайн!", []), [])
        self.assertEqual(extract_link_urls("Стрим онлайн!", None), [])

    def test_non_link_entities_ignored(self):
        # Эмодзи и упоминания не ссылки: молча пропускаются.
        entities = [custom_emoji(0), {"type": "bold", "offset": 0, "length": 3}]
        self.assertEqual(extract_link_urls("💬ab", entities), [])

    def test_empty_url_dropped(self):
        entities = [{"type": "text_link", "offset": 0, "length": 1, "url": ""}]
        self.assertEqual(extract_link_urls("ab", entities), [])

    def test_empty_text_yields_nothing(self):
        entities = [text_link(0, 1, "https://twitch.tv/tabula")]
        self.assertEqual(extract_link_urls("", entities), [])
        self.assertEqual(extract_link_urls(None, entities), [])

    def test_object_entities_supported(self):
        # aiogram отдаёт объекты MessageEntity, а не словари.
        class Entity:
            type = "text_link"
            offset = 0
            length = 6
            url = "https://twitch.tv/tabula"

        self.assertEqual(extract_link_urls("TWITCH", [Entity()]), ["https://twitch.tv/tabula"])


if __name__ == "__main__":
    unittest.main()
