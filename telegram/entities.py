"""Сущности Telegram: ссылки в подписи.

Подпись уходит в API plain text с `entities` и без `parse_mode`: ссылка
задаётся как `text_link`, а `edited_text` для защиты от эха совпадает с тем,
что вернёт Telegram.

Два неочевидных места, оба связаны с UTF-16:

  * `offset`/`length` в entities Telegram считает в кодовых единицах UTF-16,
    а индексы Python-строк — в кодовых точках. Для `💬` (U+1F4AC, выше
    BMP) это 1 символ против 2 единиц. Любая арифметика по индексам без
    `utf16_span` сдвинет все последующие ссылки.
  * Telegram передаёт `offset`/`length` для ссылок в UTF-16 единицах, поэтому
    для URL-entity нужен явный перевод обратно в индекс Python-строки.
"""

from __future__ import annotations


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
    "build_link_entity",
    "drop_entities_beyond",
    "extract_link_urls",
    "utf16_length",
    "utf16_span",
    "utf16_to_index",
]
