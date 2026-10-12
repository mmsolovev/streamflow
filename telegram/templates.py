"""Жёсткие тексты анонсов и лимиты Telegram.

Сейчас шаблоны живут здесь, а не в `.env`: по требованиям текст фиксированный,
изменяемым он станет позже, когда понадобится. Перенос в конфиг — это замена
констант на чтение `config.settings`, структура функций при этом не меняется.

Текст всегда **пересобирается целиком** из списка найденных VOD, а не
дописывается в текущий. Поэтому результат детерминирован: повторный вызов
с тем же набором ссылок даёт тот же текст, а после краша трансляции порядок
ссылок в подписи соответствует порядку стримов.

Ограничения Telegram: caption — до 1024 символов, текст сообщения — до 4096.
При превышении текст обрезается с многоточием; вызывающий код логирует это.
"""

from __future__ import annotations

from telegram.entities import (
    build_link_entity,
    drop_entities_beyond,
    utf16_length,
    utf16_span,
)


# Заголовок в готовом анонсе.
FINISHED_TITLE = "Запись стрима:"

# Надпись кликабельной ссылки на запись.
#
# Это фиксированная подпись: стандартный emoji + слово TWITCH. Ссылка в Telegram
# не показывает URL, а показывает подпись, поэтому URL в тексте не видно
# вообще — ради этого и затевался формат.
#
# Custom emoji из исходного анонса намеренно не переносятся.
VOD_LINK_LABEL = "🎥TWITCH~"

# Одна найденная запись.
FINISHED_SINGLE_TEMPLATE = "Запись стрима:\n\n🎥TWITCH~"

# Две и больше: после краша трансляции и перезапуска broadcast.
FINISHED_MULTI_TEMPLATE = "Запись стрима:\n\n{vod_links}"

CAPTION_MAX_LENGTH = 1024
MESSAGE_MAX_LENGTH = 4096

ELLIPSIS = "…"


def normalize_vod_urls(vod_urls) -> list[str]:
    """Чистые непустые URL, без повторов, порядок сохранён.

    Повторы возможны, если один и тот же VOD закрыл две задачи по разным
    stream_id: в подписи он должен встретиться один раз.
    """
    seen: set[str] = set()
    result: list[str] = []

    for raw in vod_urls or ():
        url = (raw or "").strip()
        if not url or url in seen:
            continue
        seen.add(url)
        result.append(url)

    return result


def build_finished_text(vod_urls) -> str:
    """Подпись готового анонса. Пустой список — пустая строка.

    Это то, что Telegram покажет на экране и что бот кладёт в `edited_text`.
    URL здесь нет намеренно: ссылка отображается подписью `🎥TWITCH~`, и
    видимый текст совпадает с тем, что вернётся в `edited_channel_post`.
    Именно это делает `is_own_edit` рабочим — иначе бот счёл бы эхо своей
    правки ручной правкой стримера.

    На длину НЕ обрезается: обрезку делает `fit_to_media_limit` вызывающий код,
    которому известен тип медиа в посте.
    """
    urls = normalize_vod_urls(vod_urls)
    if not urls:
        return ""

    if len(urls) == 1:
        return FINISHED_SINGLE_TEMPLATE

    return FINISHED_MULTI_TEMPLATE.format(vod_links="\n".join(VOD_LINK_LABEL for _ in urls))


def build_finished_entities(
    vod_urls,
    media_kind: str | None = None,
) -> tuple[str, list[dict]]:
    """Готовая подпись анонса: текст и список entities для Bot API.

    Возвращается пара `(text, entities)`, а не HTML. URL лежит в entity
    `text_link`, поэтому подпись всегда уходит в API как обычный текст с
    `entities`, и `parse_mode` не используется вовсе.

    На каждый лейбл кладётся `text_link` только на слово `TWITCH`. Стандартный
    emoji и символ `~` остаются обычным текстом.

    Число ссылок подбирается по лимиту Telegram здесь, а не обрезкой готового
    текста: обрезка разрезала бы лейбл пополам и оставила `🎥TWITC…` без
    ссылки. Лучше показать меньше записей, но каждая останется целой и
    кликабельной; не попавшие в подпись помечаются многоточием.

    Сущности исходного анонса сюда не переносятся: подпись переписывается
    целиком, и всё, что в ней должно быть кликабельным, задаётся явно.
    """
    urls = normalize_vod_urls(vod_urls)
    if not urls:
        return "", []

    limit = media_text_limit(media_kind)
    # Первый лейбл начинается сразу после заголовка и пустой строки, дальше
    # каждый следующий — через один перевод строки. Позиция считается
    # сложением в индексах Python-строки и один раз переводится в UTF-16.
    first_label_start = len(FINISHED_TITLE) + 2
    label_step = len(VOD_LINK_LABEL) + 1

    header_length = utf16_length(FINISHED_TITLE) + 2
    label_length = utf16_length(VOD_LINK_LABEL)

    # Столько лейблов влезает вместе с заголовком и многоточием, если часть
    # ссылок пришлось отбросить.
    room = limit - header_length - utf16_length(ELLIPSIS)
    fitting = max(0, room // (label_length + 1))
    if not fitting and limit > header_length:
        # Заголовок помещается, а лейблы — нет: подпись всё равно полезна,
        # она сообщает, что запись скоро появится.
        fitting = 0
    shown = urls[:fitting]
    dropped = len(urls) - len(shown)

    labels = "\n".join(VOD_LINK_LABEL for _ in shown)
    if not shown:
        text = FINISHED_TITLE
    elif len(shown) == 1:
        text = FINISHED_SINGLE_TEMPLATE
    else:
        text = FINISHED_MULTI_TEMPLATE.format(vod_links=labels)

    if dropped:
        text = f"{text}\n{ELLIPSIS}" if shown else f"{text} {ELLIPSIS}"

    entities: list[dict] = []

    for position, url in enumerate(shown):
        start = first_label_start + position * label_step

        # TWITCH — кликабельная ссылка
        link_start = start + 1
        link_end = link_start + len("TWITCH")

        link_offset, link_length = utf16_span(
            text,
            link_start,
            link_end,
        )

        entities.append(
            build_link_entity(
                link_offset,
                link_length,
                url,
            )
        )

    return text, entities


def media_text_limit(media_kind: str | None) -> int:
    """Лимит длины текста для поста данного типа.

    `media_kind is None` — пост без медиа, правится через `editMessageText`.
    Любой непустой `media_kind` — есть подпись, правится через
    `editMessageCaption`, и лимит у неё меньше.
    """
    return MESSAGE_MAX_LENGTH if not media_kind else CAPTION_MAX_LENGTH


def fit_to_media_limit(text: str, media_kind: str | None) -> str:
    """Обрезает текст под лимит Telegram, добавляя многоточие.

    Работает с уже отрендеренным текстом: разметки в нём больше нет, сущности
    Telegram передаёт отдельным списком, поэтому ломать нечего. Вызывающий
    код обязан следом вызвать `fit_entities`, иначе сущность, вышедшая за новую
    границу текста, приведёт к «can't parse entities» — и потеряется вся
    подпись, а не одна ссылка.

    Длина считается в UTF-16, а не в кодовых точках Python: `🎥` занимает
    одну кодовую точку и две кодовые единицы, и лимит 1024 Telegram тоже задаёт
    в единицах UTF-16. Считать по точкам значило бы отдать в API текст длиннее
    лимита и получить отказ.
    """
    limit = media_text_limit(media_kind)
    if utf16_length(text) <= limit:
        return text

    budget = max(0, limit - utf16_length(ELLIPSIS))
    # Срез идёт по кодовым точкам, но с проверкой по UTF-16: точку нельзя
    # разрезать пополам, сурогатную пару из двух точек — тоже.
    cut = 0
    used = 0
    while cut < len(text):
        width = 2 if ord(text[cut]) > 0xFFFF else 1
        if used + width > budget:
            break
        used += width
        cut += 1

    return text[:cut] + ELLIPSIS


def fit_entities(text: str, entities: list[dict]) -> list[dict]:
    """Оставляет только сущности, целиком попавшие в обрезанный текст.

    Сущность, обрезанная границей лимита, отбрасывается целиком: Telegram
    отверг бы весь caption из-за одного `offset` за пределами строки, а
    половина подписи без ссылки хуже, чем её отсутствие.

    Проверка идёт по UTF-16 и безусловно: сущности, чей конец вышел за конец
    текста, надо убрать даже когда длина текста не превысила лимит. Проверка
    «превысил ли лимит» после обрезки бесполезна — длина как раз равна лимиту,
    и она всегда дала бы ложное «нет».
    """
    return drop_entities_beyond(entities, utf16_length(text))


def is_own_edit(incoming_text: str | None, edited_text: str | None) -> bool:
    """Отличаем эхо своей правки от ручной правки стримера.

    Сравнение по полному равенству было бы слишком строгим: при обрезке под
    лимит длины строки расходятся, и Telegram может вернуть эмодзи в виде
    placeholder. Поэтому равенство не требуется — достаточно, чтобы одна
    строка была префиксом другой.

    Пустые строки не считаются своим эхом: пустой пост означает, что текст
    удалили вручную, и бот обязан отступить.
    """
    incoming = " ".join((incoming_text or "").split())
    edited = " ".join((edited_text or "").split())

    if not incoming or not edited:
        return False

    return incoming == edited or incoming.startswith(edited) or edited.startswith(incoming)


__all__ = [
    "CAPTION_MAX_LENGTH",
    "ELLIPSIS",
    "FINISHED_MULTI_TEMPLATE",
    "FINISHED_SINGLE_TEMPLATE",
    "FINISHED_TITLE",
    "MESSAGE_MAX_LENGTH",
    "VOD_LINK_LABEL",
    "build_finished_entities",
    "build_finished_text",
    "fit_entities",
    "fit_to_media_limit",
    "is_own_edit",
    "media_text_limit",
    "normalize_vod_urls",
]
