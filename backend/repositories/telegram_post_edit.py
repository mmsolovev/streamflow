"""Queries for the Telegram post-stream editing admin section."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    Stream,
    TelegramAnnouncement,
    TelegramAnnouncementVod,
    TelegramPostEditOperation,
)
from telegram import post_edit_store, vod_jobs


async def get_settings(session: AsyncSession) -> TelegramPostEditSettings:
    return await post_edit_store.get_settings(session)


async def list_runs(session: AsyncSession, limit: int = 30):
    result = await session.execute(
        select(TelegramAnnouncementVod, Stream)
        .outerjoin(Stream, Stream.external_id == TelegramAnnouncementVod.stream_id)
        .order_by(
            TelegramAnnouncementVod.stream_ended_at.desc().nulls_last(),
            TelegramAnnouncementVod.id.desc(),
        )
        .limit(limit)
    )
    return result.all()


async def get_run(session: AsyncSession, run_id: int):
    result = await session.execute(
        select(TelegramAnnouncementVod, Stream)
        .outerjoin(Stream, Stream.external_id == TelegramAnnouncementVod.stream_id)
        .where(TelegramAnnouncementVod.id == run_id)
    )
    return result.first()


async def latest_run(session: AsyncSession):
    rows = await list_runs(session, limit=1)
    return rows[0] if rows else None


async def list_announcements(session: AsyncSession, limit: int = 50):
    since = datetime.utcnow() - timedelta(days=30)
    result = await session.execute(
        select(TelegramAnnouncement)
        .where(
            TelegramAnnouncement.posted_at >= since,
            TelegramAnnouncement.status != "skipped",
        )
        .order_by(TelegramAnnouncement.posted_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_announcement(session: AsyncSession, announcement_id: int):
    return await session.get(TelegramAnnouncement, announcement_id)


async def set_target(
    session: AsyncSession,
    *,
    run_id: int,
    announcement_id: int,
    delay_seconds: int,
) -> None:
    now = datetime.utcnow()
    check_at = now + timedelta(seconds=max(delay_seconds, 0))
    await session.execute(
        update(TelegramAnnouncementVod)
        .where(TelegramAnnouncementVod.id == run_id)
        .values(
            announcement_id=announcement_id,
            selected_by_admin=True,
            status="waiting",
            check_at=check_at,
            last_error=None,
            updated_at=now,
        )
    )


async def latest_applied_operation(session: AsyncSession, run_id: int):
    result = await session.execute(
        select(TelegramPostEditOperation)
        .where(
            TelegramPostEditOperation.job_id == run_id,
            TelegramPostEditOperation.status == "applied",
        )
        .order_by(TelegramPostEditOperation.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def urls_for_announcement(session: AsyncSession, announcement_id: int) -> list[str]:
    return await vod_jobs.resolved_urls(session, announcement_id)


def announcement_preview(announcement: TelegramAnnouncement) -> str:
    text = announcement.caption_snapshot or announcement.text_snapshot or ""
    text = " ".join(text.split())
    return text[:240]
