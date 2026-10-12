"""Сущности Telegram: кастомный эмодзи из анонса и ссылки в подписи.

Почему не HTML-теги. Кастомный эмодзи из набора стикеров в Bot API
отображается только когда приходит entity типа `custom_emoji`. В `parse_mode=HTML`
для него есть обходной путь — ссылка `tg://emoji?id=...`, — но он требует
Bot API ограничивает использование custom emoji ботами: для каналов боту нужны
дополнительные имена пользователя, купленные на Fragment; Premium владельца
бота отдельно разрешает отправку в личные, групповые и супергрупповые чаты.
Entity — тот же формат, каким
Telegram сам отдаёт эмодзи, поэтому он и есть прямой путь.

Из этого следует, почему подпись уходит в API plain text с `entities` и без
`parse_mode`: два формата в одном боте разъехались бы при первой же правке,
а `edited_text` для защиты от эха должен совпадать с тем, что вернёт Telegram.

Два неочевидных места, оба связаны с UTF-16:

  * `offset`/`length` в entities Telegram считает в кодовых единицах UTF-16,
    а индексы Python-строк — в кодовых точках. Для `💬` (U+1F4AC, выше
    BMP) это 1 символ против 2 единиц. Любая арифметика по индексам без
    `utf16_span` сдвинет все последующие ссылки.
  * Эмодзи и ссылка лежат на одном участке текста — это вложенные entities,
    они поддерживаются с Bot API 6.0. Порядок в списке не важен, Telegram
    группирует их сам.
"""

from __future__ import annotations


# Типы entities, с которыми работает модуль.
LINK_ENTITY_TYPES = ("text_link", "url")
EMOJI_ENTITY_TYPE = "custom_emoji"


def _field(entity, name: str, default=None):
    """Читает поле entity, который пришёл объектом aiogram или словарём.

    aiogram отдаёт `MessageEntity`, в тестах удобнее писать словари, поэтому
    поддержаны оба варианта, а не только один.
    """
    if isinstance(entity, dict):
        return entity.get(name, default)
    return getattr(entity, name, default)


def utf16_length(text: str) -> int:
    """Длина строки в кодовых единицах UTF-16 — единицах измерения Telegram."""
    return len(text.encode("utf-16-le")) // 2


def utf16_span(text: str, start: int, end: int) -> tuple[int, int]:
    """Переводит срез Python-строки `(start, end)` в `(offset, length)` Telegram.

    `start` и `end` — индексы Python-строки (кодовые точки), результат —
    UTF-16. Считать разницу длин целых префиксов, а не символов в срезе:
    так результат не зависит от того, где именно режется строка.
    """
    return utf16_length(text[:start]), utf16_length(text[:end]) - utf16_length(text[:start])


def utf16_to_index(text: str, offset: int) -> int:
    """Обратный перевод: смещение Telegram -> индекс Python-строки.

    Нужен, чтобы достать текст участка, который Telegram пометил сущностью.
    Смещение может попасть внутрь суррогатной пары — такого смещения от
    Telegram не бывает, но пустой строкой такое значение вернуть безопаснее,
    чем slices по кривому индексу.
    """
    if offset <= 0:
        return 0

    units = 0
    for index, char in enumerate(text):
        char_units = utf16_length(char)
        # offset строго внутри суррогатной пары: такого смещения Telegram не
        # присылает, но вернуть начало символа безопаснее, чем резать строку
        # по кривому индексу и получить мусор.
        if units + char_units > offset:
            return index
        units += char_units

    return len(text)


def _bounds(entity) -> tuple[int, int]:
    offset = _field(entity, "offset", 0) or 0
    length = _field(entity, "length", 0) or 0
    return int(offset), int(offset) + int(length)


def _distance(first: tuple[int, int], second: tuple[int, int]) -> int:
    """Расстояние между диапазонами: 0, если они пересекаются или соприкасаются."""
    if first[0] <= second[1] and second[0] <= first[1]:
        return 0
    return max(second[0] - first[1], first[0] - second[1], 1)


def find_custom_emoji_id(entities) -> str | None:
    """Находит `custom_emoji_id` эмодзи, который стоит в записи со ссылкой на канал.

    Стример пишет эмодзи в подписи ссылки на канал, поэтому приоритет у того
    кастомного эмодзи, который лежит ВНУТРИ entity ссылки: вложенность — это
    и есть признак «эмодзи из записи о канале», а не отдельный значок в посте.
    Если вложенного нет, берётся ближайший к ссылке, а когда ссылок в посте
    нет вовсе — первый найденный: эмодзи в анонсе стримера один.

    Возвращает строку, а не int: Bot API отдаёт `custom_emoji_id` строкой и
    требует его в том же виде для `tg://emoji?id=`.
    """
    emojis: list[tuple[int, int, str]] = []
    links: list[tuple[int, int]] = []

    for entity in entities or ():
        entity_type = _field(entity, "type")
        if entity_type == EMOJI_ENTITY_TYPE:
            emoji_id = _field(entity, "custom_emoji_id")
            if emoji_id:
                start, end = _bounds(entity)
                emojis.append((start, end, str(emoji_id)))
        elif entity_type in LINK_ENTITY_TYPES:
            links.append(_bounds(entity))

    if not emojis:
        return None

    if links:
        inside = [
            emoji for emoji in emojis
            if any(link[0] <= emoji[0] and emoji[1] <= link[1] for link in links)
        ]
        if inside:
            return inside[0][2]

        nearest = min(
            emojis,
            key=lambda emoji: (min(_distance((emoji[0], emoji[1]), link) for link in links), emoji[0]),
        )
        return nearest[2]

    return emojis[0][2]


def extract_link_urls(text: str | None, entities) -> list[str]:
    """URL всех ссылок поста в порядке появления.

    Зачем это нужно. Стремер пишет ссылку на канал скрытой подписью
    (`💬TWITCH~`), а адрес лежит в сущности `text_link`. В тексте поста URL
    нет вообще, поэтому разбор текста его не найдёт — и анонс не привяжется
    к стриму. Здесь адрес достаётся из самих сущностей.

    Два типа и дают адрес по-разному:
      * `text_link` — адрес лежит в поле `url`, а в тексте стоит подпись;
      * `url` — адрес и есть сам текст участка, его надо вырезать.

    Порядок сохраняется, повторы и пустые значения отбрасываются: в подписи
    один и тот же URL дважды не нужен, а разбор результата не должен зависеть
    от того, в каком порядке Telegram перечислит сущности.
    """
    if not text:
        return []

    urls: list[str] = []

    for entity in entities or ():
        entity_type = _field(entity, "type")

        if entity_type == "text_link":
            url = str(_field(entity, "url") or "").strip()
        elif entity_type == "url":
            start, end = _bounds(entity)
            start = utf16_to_index(text, start)
            end = utf16_to_index(text, end)
            url = text[start:end].strip()
        else:
            continue

        if url:
            urls.append(url)

    return list(dict.fromkeys(urls))


def build_link_entity(offset: int, length: int, url: str) -> dict:
    """Сущность-ссылка: URL уходит в поле, пользователю видна подпись."""
    return {"type": "text_link", "offset": offset, "length": length, "url": url}


def build_custom_emoji_entity(offset: int, length: int, custom_emoji_id: str) -> dict:
    """Сущность кастомного эмодзи поверх того же участка текста."""
    return {
        "type": EMOJI_ENTITY_TYPE,
        "offset": offset,
        "length": length,
        "custom_emoji_id": str(custom_emoji_id),
    }


def drop_entities_beyond(entities, text_length_utf16: int) -> list[dict]:
    """Убирает сущности, вышедшие за пределы обрезанного текста.

    Обрезка под лимит Telegram укорачивает текст, и сущность, чей `offset`
    или конец `offset + length` вылез за новое значение длины, приводит к
    «can't parse entities» — отвергается весь caption, а не одна ссылка.
    Выпавшая ссылка исчезает целиком: обрезанный наполовину лейбл без ссылки
    выглядел бы хуже, чем просто исчезнувшая строка.
    """
    kept = []
    for entity in entities or ():
        offset = int(_field(entity, "offset", 0) or 0)
        length = int(_field(entity, "length", 0) or 0)
        if offset >= 0 and length > 0 and offset + length <= text_length_utf16:
            kept.append(entity)
    return kept


__all__ = [
    "EMOJI_ENTITY_TYPE",
    "LINK_ENTITY_TYPES",
    "build_custom_emoji_entity",
    "build_link_entity",
    "drop_entities_beyond",
    "extract_link_urls",
    "find_custom_emoji_id",
    "utf16_length",
    "utf16_span",
    "utf16_to_index",
]
