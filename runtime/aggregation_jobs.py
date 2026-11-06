"""Очередь отложенной агрегации `game_stats`.

После финализации runtime-сессии в `stream_stats_jobs` появляется задача с
`check_at = ended_at + STREAM_STATS_AGGREGATION_DELAY_SECONDS` (11 минут).
Столько времени нужно, чтобы TwitchTracker успел увидеть стрим: если TT
придёт раньше, runtime-агрегация не должна перетирать его `avg_viewers`.

Состояние очереди лежит в PostgreSQL, поэтому ретраи и «пропущенные» окна
переживают перезапуск процесса: задача с `check_at` в прошлом будет подхвачена
на следующем старте. Захват — `FOR UPDATE SKIP LOCKED`, как в
`telegram/vod_jobs.py`: несколько процессов не обработают одну задачу дважды.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import config.settings as settings
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import StreamRuntimeSession, StreamStatsJob
from database.db import AsyncSessionLocal
from services import stats_aggregation_service
from utils.logger import get_logger

logger = get_logger("runtime.stats_jobs")

RETRY_BASE_SECONDS = 120
RETRY_MAX_SECONDS = 1800
MAX_ATTEMPTS = 8

WORKER_ID = f"stats-worker-{uuid.uuid4().hex[:8]}"


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def next_retry_at(attempts: int) -> datetime:
    delay = min(RETRY_BASE_SECONDS * (2 ** max(attempts - 1, 0)), RETRY_MAX_SECONDS)
    return _now() + timedelta(seconds=delay)


async def claim_due(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    limit: int = 10,
) -> list[StreamStatsJob]:
    """Захватить готовые задачи, пометив их `processing`.

    Вызывающий коммитит транзакцию сразу: блокировка строк живёт до коммита,
    а сама агрегация идёт в отдельных транзакциях.
    """
    moment = now or _now()
    result = await session.execute(
        select(StreamStatsJob)
        .where(
            StreamStatsJob.status == "pending",
            StreamStatsJob.check_at <= moment,
        )
        .order_by(StreamStatsJob.check_at.asc())
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    jobs = list(result.scalars().all())
    for job in jobs:
        job.status = "processing"
        job.attempts = int(job.attempts or 0) + 1
        job.locked_at = moment
        job.locked_by = WORKER_ID
        job.updated_at = moment
    await session.flush()
    return jobs


async def mark_done(session: AsyncSession, job: StreamStatsJob) -> None:
    job.status = "done"
    job.last_error = None
    job.locked_at = None
    job.locked_by = None
    job.updated_at = _now()
    await session.flush()


async def mark_failed(
    session: AsyncSession, job: StreamStatsJob, error: str
) -> None:
    job.last_error = error[:2000]
    job.locked_at = None
    job.locked_by = None
    job.updated_at = _now()
    if int(job.attempts or 0) >= MAX_ATTEMPTS:
        job.status = "failed"
    else:
        job.status = "pending"
        job.check_at = next_retry_at(int(job.attempts or 0))
    await session.flush()


async def process_job(session: AsyncSession, job: StreamStatsJob) -> None:
    """Пересчитать агрегат по стриму задачи и обновить статусы."""
    runtime_session = await session.get(
        StreamRuntimeSession, int(job.stream_session_id)
    )
    if runtime_session is not None:
        runtime_session.status = "aggregating"
        runtime_session.updated_at = _now()

    batch = await stats_aggregation_service.recompute_stream_game_stats(
        session,
        stream_id=int(job.stream_id),
        stream_session_id=int(job.stream_session_id),
        reason="runtime_finalized",
    )

    if runtime_session is not None:
        runtime_session.status = "aggregated"
        runtime_session.finalized_at = runtime_session.finalized_at or _now()
        runtime_session.updated_at = _now()

    await mark_done(session, job)
    logger.info(
        "Aggregated game_stats for stream %s (session %s, batch %s)",
        job.stream_id,
        job.stream_session_id,
        getattr(batch, "id", None),
    )


async def process_due_jobs_once(*, limit: int = 10) -> int:
    """Один проход воркера. Возвращает число обработанных задач."""
    async with AsyncSessionLocal() as session:
        jobs = await claim_due(session, limit=limit)
        await session.commit()

    processed = 0
    for job in jobs:
        async with AsyncSessionLocal() as session:
            try:
                db_job = await session.get(StreamStatsJob, int(job.id))
                if db_job is None or db_job.status != "processing":
                    continue
                await process_job(session, db_job)
                await session.commit()
                processed += 1
            except Exception as exc:  # noqa: BLE001
                await session.rollback()
                logger.exception(
                    "Failed to aggregate stream %s (session %s)",
                    job.stream_id,
                    job.stream_session_id,
                )
                async with AsyncSessionLocal() as fail_session:
                    fail_job = await fail_session.get(StreamStatsJob, int(job.id))
                    if fail_job is not None:
                        await mark_failed(fail_session, fail_job, str(exc))
                    fail_session_db = await fail_session.get(
                        StreamRuntimeSession, int(job.stream_session_id)
                    )
                    if fail_session_db is not None:
                        fail_session_db.status = "failed"
                        fail_session_db.finalize_reason = str(exc)[:1000]
                        fail_session_db.updated_at = _now()
                    await fail_session.commit()

    return processed


async def reset_stale_processing(*, older_than_seconds: int = 3600) -> int:
    """Вернуть в очередь задачи, застрявшие в `processing` после падения."""
    moment = _now() - timedelta(seconds=older_than_seconds)
    async with AsyncSessionLocal() as session:
        updated = await session.execute(
            update(StreamStatsJob)
            .where(
                StreamStatsJob.status == "processing",
                StreamStatsJob.locked_at.is_not(None),
                StreamStatsJob.locked_at < moment,
            )
            .values(status="pending", locked_at=None, locked_by=None, updated_at=_now())
        )
        await session.commit()
        return int(updated.rowcount or 0)


class StatsAggregationWorker:
    """Фоновый воркер в процессе бота."""

    def __init__(self, interval_seconds: int | None = None):
        self.interval_seconds = max(
            int(interval_seconds or settings.STREAM_STATS_WORKER_INTERVAL_SECONDS), 1
        )
        self._task: asyncio.Task | None = None
        self._stopping = False

    async def start(self) -> None:
        if not settings.STREAM_STATS_WORKER_ENABLED:
            logger.info("Stats aggregation worker disabled by settings")
            return
        if self._task and not self._task.done():
            return
        try:
            await reset_stale_processing()
        except Exception:
            logger.exception("Failed to reset stale stats jobs")
        self._task = asyncio.get_running_loop().create_task(
            self._run(), name="stats-aggregation-worker"
        )
        logger.info(
            "Stats aggregation worker started (interval=%ss)", self.interval_seconds
        )

    async def stop(self) -> None:
        self._stopping = True
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def _run(self) -> None:
        while not self._stopping:
            try:
                await process_due_jobs_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Stats aggregation worker iteration failed")
            await asyncio.sleep(self.interval_seconds)
