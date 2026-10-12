"""Работа с таблицей `telegram_announcements`.

Разделено с логикой намерения: здесь только чтение и запись, решение «взять
пост или пропустить» принимает `matcher.py`. Так чистые функции остаются
тестируемыми без БД, а БД не знает про правила Telegram.

Идемпотентность обеспечивается UNIQUE(chat_id, message_id): повторный
`channel_post` по одному и тому же сообщению обновляет строку, а не плодит
дубли. Это важно, потому что getUpdates при реконнекте переигрывает апдейты.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import TelegramAnnouncement


# Насколько назад искать посты, уже привязанные к стримам. Нужно для
# правила переиспользования анонса после краша трансляции.
REBIND_LOOKBACK_HOURS = 12


def _now() -> datetime:
    """naive UTC — под колонки DateTime без таймзоны."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def dump_link_urls(link_urls) -> str | None:
    """Ссылки в колонку: JSON-массив, либо None когда ссылок нет.

    None, а не `[]`: пустой массив означал бы, что ссылки смотрели и не нашли,
    а None — что их и не искали, либо поста с ними не было вовсе. Разница
    видна в диагностике и стоит одного байта.
    """
    urls = [str(url).strip() for url in (link_urls or ()) if str(url or "").strip()]
    if not urls:
        return None
    return json.dumps(urls, ensure_ascii=False)


def load_link_urls(raw: str | None) -> list[str]:
    """Обратное к `dump_link_urls`.

    Пустое и битое значение даёт пустой список: колонка заполняется только
    новыми постами, и старые строки без неё должны разбираться как «ссылок
    нет», а не ронять отбор кандидата.
    """
    if not raw:
        return []
    try:
        urls = json.loads(raw)
    except (TypeError, ValueError):
        return []
    if not isinstance(urls, list):
        return []
    return [str(url).strip() for url in urls if str(url or "").strip()]


async def record_post(
    session: AsyncSession,
    *,
    chat_id: int,
    message_id: int,
    posted_at: datetime | None,
    media_kind: str | None,
    media_group_id: str | None,
    is_forward: bool,
    text: str | None,
    caption: str | None,
    custom_emoji_id: str | None = None,
    link_urls=None,
) -> int:
    """Вставляет или обновляет запись о посте. Возвращает `announcement.id`.

    Вызывается из `channel_post`. Снапшоты текста перезаписываются всегда:
    апдейт с актуальным текстом полезнее прежнего, а разбор делается позже,
    при `stream.offline`, когда текст уже точно известен.

    `custom_emoji_id` перезаписывается вместе с снапшотами по той же
    причине: он принадлежит содержимому поста, а не истории его правок.
    `link_urls` — по той же причине, плюс без них отбор кандидата в принципе
    не работает: у скрытой ссылки в тексте следа нет.
    """
    statement = (
        pg_insert(TelegramAnnouncement)
        .values(
            chat_id=chat_id,
            message_id=message_id,
            media_kind=media_kind,
            media_group_id=media_group_id,
            is_forward=bool(is_forward),
            text_snapshot=text,
            caption_snapshot=caption,
            custom_emoji_id=custom_emoji_id,
            link_urls=dump_link_urls(link_urls),
            posted_at=to_naive_utc(posted_at) or _now(),
            status="observed",
            created_at=_now(),
            updated_at=_now(),
        )
        .on_conflict_do_update(
            constraint="uq_telegram_announcements_chat_message",
            set_={
                "media_kind": media_kind,
                "media_group_id": media_group_id,
                "is_forward": bool(is_forward),
                "text_snapshot": text,
                "caption_snapshot": caption,
                "custom_emoji_id": custom_emoji_id,
                "link_urls": dump_link_urls(link_urls),
                "posted_at": to_naive_utc(posted_at) or _now(),
                "updated_at": _now(),
            },
        )
        .returning(TelegramAnnouncement.id)
    )

    result = await session.execute(statement)
    return result.scalar_one()


async def get_by_id(
    session: AsyncSession,
    announcement_id: int,
) -> TelegramAnnouncement | None:
    result = await session.execute(
        select(TelegramAnnouncement).where(TelegramAnnouncement.id == announcement_id)
    )
    return result.scalar_one_or_none()


async def get_by_chat_message(
    session: AsyncSession,
    *,
    chat_id: int,
    message_id: int,
) -> TelegramAnnouncement | None:
    result = await session.execute(
        select(TelegramAnnouncement).where(
            TelegramAnnouncement.chat_id == chat_id,
            TelegramAnnouncement.message_id == message_id,
        )
    )
    return result.scalar_one_or_none()


async def recent_posts(
    session: AsyncSession,
    *,
    chat_id: int,
    posted_after: datetime,
    posted_before: datetime | None = None,
) -> list[TelegramAnnouncement]:
    """Посты канала в окне времени — кандидаты на анонс.

    Сортировка по времени нужна для выбора самого свежего по `pick_candidate`,
    а не для красоты.
    """
    query = (
        select(TelegramAnnouncement)
        .where(
            TelegramAnnouncement.chat_id == chat_id,
            TelegramAnnouncement.posted_at >= posted_after,
        )
        .order_by(TelegramAnnouncement.posted_at.asc())
        .limit(200)
    )
    if posted_before is not None:
        query = query.where(TelegramAnnouncement.posted_at <= posted_before)

    result = await session.execute(query)
    return list(result.scalars().all())


async def recent_bound_ids(
    session: AsyncSession,
    *,
    chat_id: int,
    posted_after: datetime,
) -> set[int]:
    """message_id постов, к которым уже привязан хотя бы один стрим."""
    from database.models import TelegramAnnouncementVod

    result = await session.execute(
        select(TelegramAnnouncement.message_id)
        .join(
            TelegramAnnouncementVod,
            TelegramAnnouncementVod.announcement_id == TelegramAnnouncement.id,
        )
        .where(
            TelegramAnnouncement.chat_id == chat_id,
            TelegramAnnouncement.posted_at >= posted_after,
        )
    )
    return {row for row in result.scalars().all()}


async def mark_edited(
    session: AsyncSession,
    *,
    announcement_id: int,
    text: str,
) -> None:
    """Помечает анонс отредактированным ботом.

    Вызывается ДО вызова Bot API, и `text` кладётся в `edited_text`. Тогда
    собственный `edited_channel_post`, который вернётся следом, будет
    узнан как эхо, а не как ручная правка стримера.
    """
    await session.execute(
        update(TelegramAnnouncement)
        .where(TelegramAnnouncement.id == announcement_id)
        .values(
            status="edited",
            edited_text=text,
            manually_edited=False,
            updated_at=_now(),
        )
    )


async def mark_skipped(
    session: AsyncSession,
    *,
    announcement_id: int,
    reason: str | None = None,
) -> None:
    """Пост признан непригодным для правки (например, стример правил руками)."""
    await session.execute(
        update(TelegramAnnouncement)
        .where(TelegramAnnouncement.id == announcement_id)
        .values(
            status="skipped",
            manually_edited=bool(reason == "manual_edit"),
            updated_at=_now(),
        )
    )


async def touch_snapshots(
    session: AsyncSession,
    *,
    announcement_id: int,
    text: str | None,
    caption: str | None,
    custom_emoji_id: str | None = None,
    link_urls=None,
    media_kind: str | None = None,
    media_group_id: str | None = None,
) -> None:
    """Обновить снапшоты сообщения при `edited_channel_post`."""
    values: dict[str, object] = {
        "text_snapshot": text,
        "caption_snapshot": caption,
        "updated_at": _now(),
    }

    # Не перезаписываем None-значения, чтобы не потерять ранее установленные данные.
    if custom_emoji_id is not None:
        values["custom_emoji_id"] = custom_emoji_id
    if link_urls is not None:
        values["link_urls"] = dump_link_urls(link_urls)
    if media_kind is not None:
        values["media_kind"] = media_kind
    if media_group_id is not None:
        values["media_group_id"] = media_group_id

    await session.execute(
        update(TelegramAnnouncement)
        .where(TelegramAnnouncement.id == announcement_id)
        .values(**values)
    )


async def save_custom_emoji_id(
    session: AsyncSession,
    *,
    announcement_id: int,
    custom_emoji_id: int | None,
) -> None:
    """Запоминает кастомный эмодзи из анонса, чтобы повторить его в подписи.

    Пишется и при `None`: значит в посте кастомного эмодзи не было, и
    перезаписывать прежнее значение нельзя — иначе после ручной правки
    анонса бот продолжал бы ставить эмодзи, которого в посте уже нет.
    """
    await session.execute(
        update(TelegramAnnouncement)
        .where(TelegramAnnouncement.id == announcement_id)
        .values(
            custom_emoji_id=custom_emoji_id,
            updated_at=_now(),
        )
    )


__all__ = [
    "REBIND_LOOKBACK_HOURS",
    "dump_link_urls",
    "get_by_chat_message",
    "get_by_id",
    "load_link_urls",
    "mark_edited",
    "mark_skipped",
    "recent_bound_ids",
    "recent_posts",
    "record_post",
    "save_custom_emoji_id",
    "to_naive_utc",
]
