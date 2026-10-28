"""aiogram-обработчики апдейтов канала.

Слой намеренно тонкий: он превращает апдейт Telegram в вызов репозитория и
ничего не решает. Вся логика отбора — в `matcher.py`, весь текст — в
`templates.py`. Иначе правила разъезжаются между апдейтами и VOD-поллером.

Обрабатываются только апдейты канала: `message` из личных чатов игнорируются,
бот ничего не отправляет и не отвечает.
"""

from __future__ import annotations
from aiogram import Router
from aiogram.types import Message

from database.db import AsyncSessionLocal
from telegram import announcements
from telegram.entities import extract_link_urls
from telegram.templates import is_own_edit
from utils.logger import get_logger


logger = get_logger("telegram.handlers")

router = Router(name="telegram-channel")


def media_kind(message: Message) -> str | None:
    """Тип медиа поста: определяет метод правки.

    `editMessageCaption` работает только для медиа, `editMessageText` — только
    для постов без него. Путать их нельзя: Telegram вернёт ошибку.
    """
    if message.photo:
        return "photo"

    if message.video:
        return "video"

    if message.document:
        return "document"
    return None


def has_channel_link(message: Message) -> bool:
    """Репозиторий ждёт только канал и message_id, а текст — целиком."""
    return bool(message.chat and message.message_id)


def entities_of(message: Message) -> list:
    """Сущности поста: у медиа они в caption_entities, у текста — в entities."""
    return list(message.caption_entities or message.entities or [])


def link_urls_of(message: Message) -> list[str]:
    """Адреса ссылок поста из entities.

    Нужны потому, что стример пишет ссылку на канал скрытой подписью: в тексте
    URL нет, и без entities отбор кандидата счёл бы пост новостью.
    """
    return extract_link_urls(message.caption or message.text, entities_of(message))


async def record_announcement(session, message: Message) -> int:
    """Общий путь записи поста для обоих апдейтов."""
    return await announcements.record_post(
        session,
        chat_id=message.chat.id,
        message_id=message.message_id,
        posted_at=message.date,
        media_kind=media_kind(message),
        media_group_id=message.media_group_id,
        is_forward=message.forward_origin is not None,
        text=message.text,
        caption=message.caption,
        entities=entities_of(message),
        link_urls=link_urls_of(message),
    )

@router.channel_post()
async def on_channel_post(message: Message) -> None:
    """Новый пост в канале: запоминаем его как возможный анонс.

    Ничего не правим здесь. Привязка к стриму происходит на `stream.offline`,
    когда известны границы трансляции и можно проверить окно времени.
    """
    if not has_channel_link(message):
        return

    try:
        async with AsyncSessionLocal() as session:
            await record_announcement(session, message)
            await session.commit()
    except Exception:
        logger.exception("Failed to record channel post %s", message.message_id)
        return

    logger.info(
        "Observed channel post %s in chat %s (media=%s, forward=%s)",
        message.message_id,
        message.chat.id,
        media_kind(message),
        message.forward_origin is not None,
    )


@router.edited_channel_post()
async def on_edited_channel_post(message: Message) -> None:
    """Пост в канале изменили.

    Два случая, и их важно различать:
      - правка стримера: бот обязан отступить и больше не трогать пост;
      - эхо собственной правки бота: иначе бот посчитает свой же текст
        ручной правкой, снял бы задачу с поста и потерял бы вторую ссылку
        после краша трансляции.

    Различаются по `announcements.edited_text`: там лежит текст, который
    записывал бот.
    """
    if not has_channel_link(message):
        return

    try:
        async with AsyncSessionLocal() as session:
            existing = await announcements.get_by_chat_message(
                session,
                chat_id=message.chat.id,
                message_id=message.message_id,
            )
            if existing is None:
                # Пост отредактирован раньше, чем бот его увидел: заводим запись,
                # чтобы он не потерялся как кандидат.
                await record_announcement(session, message)
                await session.commit()
                return

            await announcements.touch_snapshots(
                session,
                announcement_id=existing.id,
                text=message.text,
                caption=message.caption,
                entities=entities_of(message),
                link_urls=link_urls_of(message),
                media_kind=media_kind(message),
                media_group_id=message.media_group_id,
            )

            incoming = message.caption or message.text
            is_own_echo = existing.edited_text is not None and is_own_edit(
                incoming, existing.edited_text
            )

            if not is_own_echo and existing.status == "edited":
                await announcements.mark_skipped(
                    session,
                    announcement_id=existing.id,
                    reason="manual_edit",
                )
                logger.info(
                    "Announcement %s edited by someone else, skipping further edits",
                    existing.id,
                )

            await session.commit()
    except Exception:
        logger.exception("Failed to handle edited channel post %s", message.message_id)


__all__ = [
    "entities_of",
    "link_urls_of",
    "media_kind",
    "on_channel_post",
    "on_edited_channel_post",
    "record_announcement",
    "router",
]
