"""Database access for configurable post-stream editing."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import TelegramAnnouncementVod, TelegramPostEditSettings
from telegram.post_edit import (
    DEFAULT_DELAY_SECONDS,
    DEFAULT_FOOTER,
    DEFAULT_HEADER,
    DEFAULT_ITEM,
    DEFAULT_LINK_LABEL,
    DEFAULT_SEPARATOR,
    PostEditTemplate,
)

SETTINGS_ID = 1


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def get_settings(session: AsyncSession) -> TelegramPostEditSettings:
    row = await session.get(TelegramPostEditSettings, SETTINGS_ID)
    if row is None:
        row = TelegramPostEditSettings(
            id=SETTINGS_ID,
            enabled=True,
            delay_seconds=DEFAULT_DELAY_SECONDS,
            header=DEFAULT_HEADER,
            item=DEFAULT_ITEM,
            separator=DEFAULT_SEPARATOR,
            footer=DEFAULT_FOOTER,
            link_label=DEFAULT_LINK_LABEL,
        )
        session.add(row)
        await session.flush()
    return row


def template_from_settings(row: TelegramPostEditSettings) -> PostEditTemplate:
    return PostEditTemplate(
        header=row.header,
        item=row.item,
        separator=row.separator,
        footer=row.footer,
        link_label=row.link_label,
    )


async def reschedule_waiting(session: AsyncSession, delay_seconds: int) -> None:
    now = _now()
    result = await session.execute(
        select(TelegramAnnouncementVod).where(
            TelegramAnnouncementVod.status == "waiting",
            TelegramAnnouncementVod.announcement_id.is_not(None),
        )
    )
    for job in result.scalars().all():
        ended_at = job.stream_ended_at or job.stream_started_at
        job.check_at = max(now, ended_at + timedelta(seconds=max(delay_seconds, 0)))
        job.updated_at = now


__all__ = [
    "SETTINGS_ID",
    "get_settings",
    "reschedule_waiting",
    "template_from_settings",
]
