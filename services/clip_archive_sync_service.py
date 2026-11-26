"""Rate-limited, resumable synchronization of Twitch clips."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import config.settings as settings
from database.db import AsyncSessionLocal
from database.models import (
    Clip,
    ClipSyncJob,
    ClipSyncState,
    Stream,
    StreamRuntimeSession,
)
from sqlalchemy import select
from utils.logger import get_logger

logger = get_logger("clips.archive_sync")
RECENT_STATE_KEY = "recent_ingest"
METRICS_STATE_KEY = "metrics_refresh"
LIVE_METRICS_STATE_KEY = "live_metrics_refresh"
CLIP_CREATED_AT_OVERLAP = timedelta(minutes=15)
MAX_CLIP_QUERY_AGE = timedelta(days=6)
EVENT_RECOVERY_AGE = timedelta(days=3)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_naive_utc(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


class ClipArchiveSyncWorker:
    """Keeps new, popular, and older clips fresh without rescanning history."""

    def __init__(self, *, poll_seconds: int = 60):
        self.poll_seconds = max(30, int(poll_seconds))
        self._task: asyncio.Task | None = None
        self._stopping = False
        self._last_recovery_at: datetime | None = None
        self._recent_retry_at: datetime | None = None
        self._metrics_retry_at: datetime | None = None
        self._live_metrics_retry_at: datetime | None = None

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stopping = False
        self._task = asyncio.get_running_loop().create_task(
            self._run(), name="twitch-clip-archive-sync"
        )
        logger.info(
            "Clip sync worker started (live ingest=%ss, offline ingest=%ss, live metrics=%ss, offline metrics=%ss)",
            settings.TWITCH_CLIP_SYNC_INTERVAL_SECONDS,
            settings.TWITCH_CLIP_OFFLINE_SYNC_INTERVAL_SECONDS,
            settings.TWITCH_CLIP_LIVE_METRICS_INTERVAL_SECONDS,
            settings.TWITCH_CLIP_METRICS_INTERVAL_SECONDS,
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

    async def on_stream_finalized(self, snapshot: dict) -> None:
        """Persist a full-stream clip refresh due 12 minutes after finalization."""
        stream_db_id = snapshot.get("stream_db_id")
        ended_at = _as_naive_utc(snapshot.get("ended_at"))
        if stream_db_id is None or ended_at is None:
            logger.warning("Cannot schedule clip refresh: incomplete stream snapshot")
            return
        stream_db_id = int(stream_db_id)
        now = _now()
        check_at = ended_at + timedelta(
            seconds=settings.TWITCH_CLIP_FINAL_REFRESH_DELAY_SECONDS
        )
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ClipSyncJob).where(ClipSyncJob.stream_id == stream_db_id)
            )
            job = result.scalar_one_or_none()
            if job is None:
                session.add(
                    ClipSyncJob(
                        stream_id=stream_db_id,
                        check_at=check_at,
                        status="pending",
                        attempts=0,
                        created_at=now,
                        updated_at=now,
                    )
                )
            elif job.status != "completed":
                job.check_at = check_at
                job.status = "pending"
                job.last_error = None
                job.updated_at = now
            await session.commit()
        logger.info(
            "Scheduled post-stream clip refresh for database stream %s at %s",
            stream_db_id,
            check_at,
        )

    async def _recover_recent_finalizations(self) -> None:
        now = _now()
        if (
            self._last_recovery_at is not None
            and (now - self._last_recovery_at).total_seconds() < 3600
        ):
            return
        self._last_recovery_at = now
        cutoff = now - EVENT_RECOVERY_AGE
        async with AsyncSessionLocal() as session:
            stuck_result = await session.execute(
                select(ClipSyncJob).where(
                    ClipSyncJob.status == "running",
                    ClipSyncJob.updated_at <= now - timedelta(minutes=30),
                )
            )
            stuck_jobs = list(stuck_result.scalars().all())
            for job in stuck_jobs:
                job.status = "pending"
                job.check_at = now
                job.updated_at = now

            result = await session.execute(
                select(StreamRuntimeSession)
                .where(
                    StreamRuntimeSession.ended_at.is_not(None),
                    StreamRuntimeSession.finalized_at >= cutoff,
                    ~select(ClipSyncJob.id)
                    .where(ClipSyncJob.stream_id == StreamRuntimeSession.stream_id)
                    .exists(),
                )
            )
            sessions = list(result.scalars().all())
            for runtime_session in sessions:
                ended_at = runtime_session.ended_at
                if ended_at is None:
                    continue
                session.add(
                    ClipSyncJob(
                        stream_id=int(runtime_session.stream_id),
                        check_at=ended_at
                        + timedelta(
                            seconds=settings.TWITCH_CLIP_FINAL_REFRESH_DELAY_SECONDS
                        ),
                        status="pending",
                        attempts=0,
                        created_at=now,
                        updated_at=now,
                    )
                )
            if sessions or stuck_jobs:
                await session.commit()
                logger.info(
                    "Recovered %d missed finalization(s) and %d interrupted clip job(s)",
                    len(sessions),
                    len(stuck_jobs),
                )

    async def _current_live_stream_id(self) -> int | None:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(StreamRuntimeSession.stream_id)
                .where(StreamRuntimeSession.status == "collecting")
                .order_by(StreamRuntimeSession.started_at.desc())
                .limit(1)
            )
            value = result.scalar_one_or_none()
            return int(value) if value is not None else None

    async def _sync_recent_clips(self) -> None:
        now = _now()
        if self._recent_retry_at is not None and now < self._recent_retry_at:
            return
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ClipSyncState).where(
                    ClipSyncState.state_key == RECENT_STATE_KEY
                )
            )
            state = result.scalar_one_or_none()
            cursor_at = state.cursor_at if state else None
            if cursor_at is None:
                cursor_at = now - timedelta(days=1)
            started_at = cursor_at - CLIP_CREATED_AT_OVERLAP
            window_end = min(now, started_at + MAX_CLIP_QUERY_AGE)

        # This import is intentionally delayed: CLI sync remains usable without
        # starting the bot worker, and transient errors do not advance cursor_at.
        from database.sync_clips import sync_clips_window

        try:
            inserted = await sync_clips_window(started_at, window_end)
        except Exception:
            self._recent_retry_at = _now() + timedelta(minutes=5)
            raise
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ClipSyncState).where(
                    ClipSyncState.state_key == RECENT_STATE_KEY
                )
            )
            state = result.scalar_one_or_none()
            if state is None:
                state = ClipSyncState(
                    state_key=RECENT_STATE_KEY,
                    cursor_at=window_end,
                    last_completed_at=now,
                    updated_at=now,
                )
                session.add(state)
            else:
                state.cursor_at = window_end
                state.last_completed_at = now
                state.updated_at = now
            await session.commit()
        self._recent_retry_at = None
        logger.info(
            "Recent clip sync completed: inserted=%d, range=%s..%s",
            inserted,
            started_at,
            window_end,
        )

    async def _process_due_stream_jobs(self) -> None:
        now = _now()
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ClipSyncJob)
                .where(
                    ClipSyncJob.status == "pending",
                    ClipSyncJob.check_at <= now,
                )
                .order_by(ClipSyncJob.check_at)
                .limit(3)
                .with_for_update(skip_locked=True)
            )
            jobs = list(result.scalars().all())
            for job in jobs:
                job.status = "running"
                job.updated_at = now
            if jobs:
                await session.commit()

        for job in jobs:
            try:
                async with AsyncSessionLocal() as session:
                    stream = await session.get(Stream, int(job.stream_id))
                    if stream is None or stream.started_at is None:
                        raise RuntimeError("Stream row or started_at is missing")
                    stream_ended_at = stream.ended_at or now
                    refresh_through = min(
                        _now(),
                        stream_ended_at + timedelta(days=1),
                    )
                    start_at = stream.started_at
                    stream_id = int(stream.id)

                from database.sync_clips import sync_clips_window

                await sync_clips_window(start_at, refresh_through)
                async with AsyncSessionLocal() as session:
                    current = await session.get(ClipSyncJob, int(job.id))
                    if current is not None:
                        current.status = "completed"
                        current.completed_at = _now()
                        current.updated_at = current.completed_at
                        current.last_error = None
                        await session.commit()
                logger.info("Post-stream clip refresh completed for stream %s", stream_id)
            except Exception as exc:
                logger.exception("Post-stream clip refresh failed for job %s", job.id)
                async with AsyncSessionLocal() as session:
                    current = await session.get(ClipSyncJob, int(job.id))
                    if current is not None:
                        current.attempts += 1
                        current.last_error = str(exc)[:2000]
                        current.status = "pending"
                        current.check_at = _now() + timedelta(
                            seconds=min(3600, 60 * (2 ** min(current.attempts, 6)))
                        )
                        current.updated_at = _now()
                        await session.commit()

    async def _refresh_important_metrics(self) -> None:
        now = _now()
        if self._metrics_retry_at is not None and now < self._metrics_retry_at:
            return
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ClipSyncState).where(
                    ClipSyncState.state_key == METRICS_STATE_KEY
                )
            )
            state = result.scalar_one_or_none()
            if (
                state is not None
                and state.last_completed_at is not None
                and (now - state.last_completed_at).total_seconds()
                < settings.TWITCH_CLIP_METRICS_INTERVAL_SECONDS
            ):
                return

            batch_size = settings.TWITCH_CLIP_METRICS_BATCH_SIZE
            popular_result = await session.execute(
                select(Clip.external_id)
                .where(Clip.external_id.is_not(None))
                .order_by(Clip.views_count.desc().nullslast(), Clip.created_at.desc())
                .limit(batch_size // 2)
            )
            recent_result = await session.execute(
                select(Clip.external_id)
                .where(Clip.external_id.is_not(None))
                .order_by(Clip.created_at.desc())
                .limit(batch_size // 4)
            )
            stale_result = await session.execute(
                select(Clip.external_id)
                .where(Clip.external_id.is_not(None))
                .order_by(Clip.synced_at.asc().nullsfirst(), Clip.created_at.desc())
                .limit(batch_size // 4)
            )
            ids = list(
                dict.fromkeys(
                    str(row[0])
                    for result in (popular_result, recent_result, stale_result)
                    for row in result.all()
                    if row[0]
                )
            )[:batch_size]

        try:
            if ids:
                from database.sync_clips import refresh_clip_metrics

                updated = await refresh_clip_metrics(ids)
            else:
                updated = 0
        except Exception:
            self._metrics_retry_at = _now() + timedelta(minutes=15)
            raise

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ClipSyncState).where(
                    ClipSyncState.state_key == METRICS_STATE_KEY
                )
            )
            state = result.scalar_one_or_none()
            if state is None:
                state = ClipSyncState(
                    state_key=METRICS_STATE_KEY,
                    last_completed_at=now,
                    updated_at=now,
                )
                session.add(state)
            else:
                state.last_completed_at = now
                state.updated_at = now
            await session.commit()
        self._metrics_retry_at = None
        logger.info("Clip metrics refresh completed: updated=%d", updated)

    async def _refresh_live_metrics(self) -> None:
        now = _now()
        if self._live_metrics_retry_at is not None and now < self._live_metrics_retry_at:
            return
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ClipSyncState).where(
                    ClipSyncState.state_key == LIVE_METRICS_STATE_KEY
                )
            )
            state = result.scalar_one_or_none()
            if (
                state is not None
                and state.last_completed_at is not None
                and (now - state.last_completed_at).total_seconds()
                < settings.TWITCH_CLIP_LIVE_METRICS_INTERVAL_SECONDS
            ):
                return

            batch_size = settings.TWITCH_CLIP_METRICS_BATCH_SIZE
            top_result = await session.execute(
                select(Clip.external_id)
                .where(Clip.external_id.is_not(None))
                .order_by(Clip.views_count.desc().nullslast(), Clip.created_at.desc())
                .limit(batch_size // 2)
            )
            recent_result = await session.execute(
                select(Clip.external_id)
                .where(
                    Clip.external_id.is_not(None),
                    Clip.created_at >= now - timedelta(days=1),
                )
                .order_by(Clip.created_at.desc())
                .limit(batch_size // 2)
            )
            ids = list(
                dict.fromkeys(
                    str(row[0])
                    for result in (top_result, recent_result)
                    for row in result.all()
                    if row[0]
                )
            )[:batch_size]

        try:
            if ids:
                from database.sync_clips import refresh_clip_metrics

                updated = await refresh_clip_metrics(ids)
            else:
                updated = 0
        except Exception:
            self._live_metrics_retry_at = _now() + timedelta(minutes=15)
            raise

        completed_at = _now()
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(ClipSyncState).where(
                    ClipSyncState.state_key == LIVE_METRICS_STATE_KEY
                )
            )
            state = result.scalar_one_or_none()
            if state is None:
                state = ClipSyncState(
                    state_key=LIVE_METRICS_STATE_KEY,
                    last_completed_at=completed_at,
                    updated_at=completed_at,
                )
                session.add(state)
            else:
                state.last_completed_at = completed_at
                state.updated_at = completed_at
            await session.commit()
        self._live_metrics_retry_at = None
        logger.info("Live popular/recent clip metrics refreshed: updated=%d", updated)

    async def _run(self) -> None:
        while not self._stopping:
            try:
                await self._recover_recent_finalizations()
                await self._process_due_stream_jobs()
                live_stream_id = await self._current_live_stream_id()
                if live_stream_id is not None:
                    now = _now()
                    async with AsyncSessionLocal() as session:
                        result = await session.execute(
                            select(ClipSyncState).where(
                                ClipSyncState.state_key == RECENT_STATE_KEY
                            )
                        )
                        state = result.scalar_one_or_none()
                        last_run = state.last_completed_at if state else None
                    if (
                        last_run is None
                        or (now - last_run).total_seconds()
                        >= settings.TWITCH_CLIP_SYNC_INTERVAL_SECONDS
                    ):
                        await self._sync_recent_clips()
                    await self._refresh_live_metrics()
                else:
                    now = _now()
                    async with AsyncSessionLocal() as session:
                        result = await session.execute(
                            select(ClipSyncState).where(
                                ClipSyncState.state_key == RECENT_STATE_KEY
                            )
                        )
                        state = result.scalar_one_or_none()
                        last_run = state.last_completed_at if state else None
                    if (
                        last_run is None
                        or (now - last_run).total_seconds()
                        >= settings.TWITCH_CLIP_OFFLINE_SYNC_INTERVAL_SECONDS
                    ):
                        await self._sync_recent_clips()
                    await self._refresh_important_metrics()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Twitch clip archive synchronization failed")
            await asyncio.sleep(self.poll_seconds)
