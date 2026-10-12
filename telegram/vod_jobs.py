"""Работа с таблицей `telegram_announcement_vods`: очередь задач «найти VOD».

Задача, а не колонка в анонсе, потому что после краша трансляции и перезапуска
broadcast один и тот же пост получает два разных VOD — по одному на Twitch
`stream_id`. У каждого своя готовность, свои попытки и своя ошибка.

Очередь опрашивается по `check_at`, поэтому ретраи переживают перезапуск
процесса: состояние лежит в БД, а не в памяти.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import TelegramAnnouncementVod


# Интервал между попытками при инфраструктурной ошибке. Растёт, чтобы не
# долбить Twitch API, когда он лежит.
RETRY_BASE_SECONDS = 120
RETRY_MAX_SECONDS = 1800

# Анонсы, у которых уже есть завершённые VOD-строки, — кандидаты на
# переиспользование поста после краша трансляции.
REBIND_LOOKBACK_HOURS = 12


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def next_retry_at(attempts: int) -> datetime:
    """Время следующей попытки с растущей паузой."""
    delay = min(RETRY_BASE_SECONDS * (2 ** max(attempts - 1, 0)), RETRY_MAX_SECONDS)
    return _now() + timedelta(seconds=delay)


async def create_job(
    session: AsyncSession,
    *,
    announcement_id: int,
    stream_id: str,
    stream_started_at: datetime | None,
    stream_ended_at: datetime | None,
    check_delay_seconds: int,
) -> int | None:
    """Ставит задачу в очередь. Повторный вызов для того же стрима — no-op.

    Возвращает id созданной задачи либо None, если задача уже была.
    Идемпотентность обеспечивает UNIQUE(announcement_id, stream_id): при
    повторном `stream.offline` или реконнекте задача не задваивается.
    """
    started = to_naive_utc(stream_started_at) or _now()

    statement = (
        pg_insert(TelegramAnnouncementVod)
        .values(
            announcement_id=announcement_id,
            stream_id=str(stream_id),
            stream_started_at=started,
            stream_ended_at=to_naive_utc(stream_ended_at),
            status="waiting",
            attempts=0,
            # VOD появляется не мгновенно, поэтому первая проверка отложена.
            check_at=_now() + timedelta(seconds=max(check_delay_seconds, 0)),
            created_at=_now(),
            updated_at=_now(),
        )
        .on_conflict_do_nothing(constraint="uq_telegram_announcement_vods_announcement_stream")
        .returning(TelegramAnnouncementVod.id)
    )

    result = await session.execute(statement)
    return result.scalar_one_or_none()


async def claim_due(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    limit: int = 10,
) -> list[TelegramAnnouncementVod]:
    """Забирает задачи, готовые к проверке.

    `FOR UPDATE SKIP LOCKED`: если два процесса поднимут поллер на одном
    посте (например, старая ревизия ещё жива), задачу обработает только один.
    Без этого возможны двойные правки одного поста.
    """
    moment = now or _now()

    result = await session.execute(
        select(TelegramAnnouncementVod)
        .where(
            TelegramAnnouncementVod.status == "waiting",
            TelegramAnnouncementVod.check_at <= moment,
        )
        .order_by(TelegramAnnouncementVod.check_at.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return list(result.scalars().all())


async def get_by_id(
    session: AsyncSession,
    job_id: int,
) -> TelegramAnnouncementVod | None:
    result = await session.execute(
        select(TelegramAnnouncementVod).where(TelegramAnnouncementVod.id == job_id)
    )
    return result.scalar_one_or_none()


async def jobs_for_announcement(
    session: AsyncSession,
    announcement_id: int,
) -> list[TelegramAnnouncementVod]:
    """Все задачи анонса, в порядке начала стримов.

    Порядок важен: по нему собирается текст подписи, чтобы ссылки шли
    хронологически, а не в случайном порядке выборки.
    """
    result = await session.execute(
        select(TelegramAnnouncementVod)
        .where(TelegramAnnouncementVod.announcement_id == announcement_id)
        .order_by(TelegramAnnouncementVod.stream_started_at.asc())
    )
    return list(result.scalars().all())


async def resolved_urls(session: AsyncSession, announcement_id: int) -> list[str]:
    """Ссылки на найденные VOD, хронологически."""
    jobs = await jobs_for_announcement(session, announcement_id)
    return [job.vod_url for job in jobs if job.status == "resolved" and job.vod_url]


async def mark_resolved(
    session: AsyncSession,
    *,
    job_id: int,
    vod_url: str,
    duration_minutes: int | None = None,
    recorded_at: datetime | None = None,
) -> None:
    await session.execute(
        update(TelegramAnnouncementVod)
        .where(TelegramAnnouncementVod.id == job_id)
        .values(
            status="resolved",
            vod_url=vod_url,
            duration_minutes=duration_minutes,
            recorded_at=to_naive_utc(recorded_at),
            last_error=None,
            updated_at=_now(),
        )
    )


async def mark_no_vod(
    session: AsyncSession,
    *,
    job_id: int,
    reason: str,
    attempts: int,
) -> None:
    """Терминальный исход: VOD в архиве нет, ждать бессмысленно.

    Пост при этом не трогаем — требование «молча не ломать».
    """
    await session.execute(
        update(TelegramAnnouncementVod)
        .where(TelegramAnnouncementVod.id == job_id)
        .values(
            status="no_vod",
            attempts=attempts,
            last_error=reason,
            updated_at=_now(),
        )
    )


async def mark_failed(
    session: AsyncSession,
    *,
    job_id: int,
    error: str,
    attempts: int,
    max_attempts: int,
) -> bool:
    """Инфраструктурная ошибка. Возвращает True, если попытки исчерпаны.

    Исчерпание попыток переводит задачу в `failed`, а не в `no_vod`: это
    разные диагностические состояния — «Twitch не отдал» и «сломались» .
    """
    if attempts >= max_attempts:
        await session.execute(
            update(TelegramAnnouncementVod)
            .where(TelegramAnnouncementVod.id == job_id)
            .values(
                status="failed",
                attempts=attempts,
                last_error=error,
                updated_at=_now(),
            )
        )
        return True

    await session.execute(
        update(TelegramAnnouncementVod)
        .where(TelegramAnnouncementVod.id == job_id)
        .values(
            attempts=attempts,
            last_error=error,
            check_at=next_retry_at(attempts),
            updated_at=_now(),
        )
    )
    return False


async def recent_finished_streams(
    session: AsyncSession,
    *,
    since: datetime,
) -> list[tuple[int, str | None]]:
    """id анонса и `stream_ended_at` его последнего завершённого стрима.

    Основа правила переиспользования: после краша нового анонса нет, и VOD
    нового стрима дописывается в тот же пост.
    """
    result = await session.execute(
        select(
            TelegramAnnouncementVod.announcement_id,
            TelegramAnnouncementVod.stream_ended_at,
        )
        .where(
            TelegramAnnouncementVod.status == "resolved",
            TelegramAnnouncementVod.stream_ended_at.is_not(None),
            TelegramAnnouncementVod.stream_ended_at >= since,
        )
        .order_by(TelegramAnnouncementVod.stream_ended_at.desc())
    )
    return [(row[0], row[1]) for row in result.all()]


__all__ = [
    "REBIND_LOOKBACK_HOURS",
    "RETRY_BASE_SECONDS",
    "RETRY_MAX_SECONDS",
    "claim_due",
    "create_job",
    "get_by_id",
    "jobs_for_announcement",
    "mark_failed",
    "mark_no_vod",
    "mark_resolved",
    "next_retry_at",
    "recent_finished_streams",
    "resolved_urls",
    "to_naive_utc",
]
