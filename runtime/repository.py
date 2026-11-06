"""PostgreSQL-слой runtime-коллектора.

Здесь живёт вся работа с БД для самосбора статистики стримов:

- `resolve_stream` — сопоставление Twitch stream_id со строкой `streams`;
- `claim_session` — одна runtime-сессия на строку `streams` (реконнект не
  создаёт второй стрим);
- `insert_sample` / `upsert_bucket` — инкрементальная запись сэмплов;
- `build_session_snapshot` — восстановление in-memory-снимка из БД для
  `!время`, метрик и финализации;
- `finalize_session` — запись `streams`, `stream_titles`, `stream_games` и
  постановка задачи отложенной агрегации.

Даты в БД — naive UTC; в снимок они сериализуются с tzinfo=UTC, чтобы
существующие функции `runtime.metrics` работали с aware datetime.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import config.settings as settings
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    Game,
    Stream,
    StreamGame,
    StreamRuntimeBucket,
    StreamRuntimeSample,
    StreamRuntimeSession,
    StreamStatsJob,
    StreamTitle,
)
from pipeline.load.load_games import get_or_create_game
from utils.logger import get_logger

logger = get_logger("runtime.repository")

STARTED_AT_TOLERANCE_MINUTES = 30
COLLECTOR_VERSION = 3
BUCKET_MINUTES = 10


# ============================================================
# TIME HELPERS
# ============================================================


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc).isoformat()


def _floor_bucket(value: datetime) -> datetime:
    value = value.replace(second=0, microsecond=0)
    return value.replace(minute=value.minute - (value.minute % BUCKET_MINUTES))


# ============================================================
# STREAM RESOLUTION
# ============================================================


async def resolve_stream(
    db: AsyncSession,
    *,
    twitch_stream_id: str,
    started_at: datetime,
    title: str | None = None,
) -> Stream:
    """Найти или создать строку `streams` для Twitch stream_id.

    Приоритет: external_id → started_at ±30 мин (как TT) → новая строка.
    Если кандидат с другим external_id завершился недавно, это реконнект:
    строку переиспользуем, но external_id не перезаписываем.
    """
    twitch_stream_id = str(twitch_stream_id)
    started_at = to_naive_utc(started_at)
    now = utcnow()

    result = await db.execute(
        select(Stream).where(Stream.external_id == twitch_stream_id)
    )
    stream = result.scalars().first()
    if stream is not None:
        if title and not stream.title:
            stream.title = title
            stream.updated_at = now
        return stream

    tolerance = timedelta(minutes=STARTED_AT_TOLERANCE_MINUTES)
    result = await db.execute(
        select(Stream).where(
            Stream.started_at.isnot(None),
            Stream.started_at.between(started_at - tolerance, started_at + tolerance),
        )
    )
    candidates = list(result.scalars().all())

    # TT мог создать строку без external_id — это тот же стрим.
    for candidate in candidates:
        if candidate.external_id == twitch_stream_id:
            return candidate
    for candidate in candidates:
        if candidate.external_id is None:
            candidate.external_id = twitch_stream_id
            candidate.updated_at = now
            if title and not candidate.title:
                candidate.title = title
            return candidate

    # Реконнект: broadcast упал и Twitch выдал новый stream_id.
    reconnect_window = timedelta(seconds=settings.STREAM_RECONNECT_WINDOW_SECONDS)
    for candidate in sorted(
        candidates,
        key=lambda s: abs((s.started_at - started_at).total_seconds()),
    ):
        ended_at = candidate.ended_at
        if ended_at is None or abs(started_at - ended_at) <= reconnect_window:
            logger.info(
                "Reusing stream %s for Twitch stream %s (reconnect)",
                candidate.id,
                twitch_stream_id,
            )
            return candidate

    # Долгий эфир: новый stream_id пришёл через часы после старта, поэтому
    # started_at-допуск не сработал. Склеиваем по свежему ended_at.
    result = await db.execute(
        select(Stream)
        .where(
            Stream.external_id.isnot(None),
            Stream.external_id != twitch_stream_id,
            Stream.ended_at.isnot(None),
            Stream.ended_at.between(
                started_at - reconnect_window,
                started_at + reconnect_window,
            ),
        )
        .order_by(Stream.ended_at.desc())
        .limit(1)
    )
    recent = result.scalars().first()
    if recent is not None:
        logger.info(
            "Reusing stream %s for Twitch stream %s (reconnect after ended_at)",
            recent.id,
            twitch_stream_id,
        )
        return recent

    stream = Stream(
        external_id=twitch_stream_id,
        started_at=started_at,
        title=title,
        created_at=now,
        updated_at=now,
    )
    db.add(stream)
    await db.flush()
    logger.info("Created stream %s for Twitch stream %s", stream.id, twitch_stream_id)
    return stream


# ============================================================
# SESSIONS
# ============================================================


async def get_collecting_sessions(db: AsyncSession) -> list[StreamRuntimeSession]:
    result = await db.execute(
        select(StreamRuntimeSession)
        .where(StreamRuntimeSession.status == "collecting")
        .order_by(StreamRuntimeSession.started_at)
    )
    return list(result.scalars().all())


async def get_session_by_stream(
    db: AsyncSession, stream_id: int
) -> StreamRuntimeSession | None:
    result = await db.execute(
        select(StreamRuntimeSession).where(StreamRuntimeSession.stream_id == stream_id)
    )
    return result.scalar_one_or_none()


async def cancel_pending_jobs(db: AsyncSession, session_id: int) -> None:
    await db.execute(
        update(StreamStatsJob)
        .where(
            StreamStatsJob.stream_session_id == session_id,
            StreamStatsJob.status.in_(("pending", "processing", "failed")),
        )
        .values(status="cancelled", updated_at=utcnow())
    )


async def claim_session(
    db: AsyncSession,
    *,
    stream: Stream,
    twitch_stream_id: str,
    started_at: datetime,
    broadcaster_id: int | None,
) -> StreamRuntimeSession:
    """Создать сессию или переоткрыть существующую для того же `streams`."""
    now = utcnow()
    started_at = to_naive_utc(started_at)
    session = await get_session_by_stream(db, int(stream.id))

    if session is None:
        session = StreamRuntimeSession(
            stream_id=int(stream.id),
            twitch_stream_id=str(twitch_stream_id),
            broadcaster_id=broadcaster_id,
            status="collecting",
            started_at=started_at,
            collector_version=COLLECTOR_VERSION,
            samples_count=0,
            created_at=now,
            updated_at=now,
        )
        db.add(session)
        await db.flush()
        return session

    if session.status != "collecting":
        await cancel_pending_jobs(db, int(session.id))
        session.status = "collecting"
        session.ended_at = None
        session.finalized_at = None
        session.finalize_reason = None

    session.twitch_stream_id = str(twitch_stream_id)
    session.broadcaster_id = broadcaster_id or session.broadcaster_id
    session.updated_at = now
    await db.flush()
    return session


async def reopen_session_for_reconnect(
    db: AsyncSession,
    session: StreamRuntimeSession,
    *,
    twitch_stream_id: str,
) -> bool:
    """Склеить новый Twitch stream_id с текущей сессией, если это реконнект.

    Возвращает True, если stream_id обновлён (эфир продолжается).
    """
    if session.twitch_stream_id == str(twitch_stream_id):
        return True

    anchor = session.ended_at or session.last_sample_at or session.started_at
    window = timedelta(seconds=settings.STREAM_RECONNECT_WINDOW_SECONDS)
    if anchor is not None and utcnow() - anchor > window:
        return False

    session.twitch_stream_id = str(twitch_stream_id)
    session.status = "collecting"
    session.ended_at = None
    session.finalized_at = None
    session.finalize_reason = None
    session.updated_at = utcnow()
    await cancel_pending_jobs(db, int(session.id))
    await db.flush()
    logger.info(
        "Session %s continued with new Twitch stream %s", session.id, twitch_stream_id
    )
    return True


# ============================================================
# SAMPLES AND BUCKETS
# ============================================================


async def insert_sample(
    db: AsyncSession,
    *,
    session: StreamRuntimeSession,
    sampled_at: datetime,
    viewers: int | None,
    followers: int | None,
    title: str | None,
    category_name: str | None,
    category_id: str | None,
    source: str,
) -> bool:
    """Вставить сэмпл (идемпотентно) и обновить бакет + прогресс сессии."""
    sampled_at = to_naive_utc(sampled_at)
    stream_id = int(session.stream_id)

    stmt = (
        pg_insert(StreamRuntimeSample)
        .values(
            stream_id=stream_id,
            stream_session_id=int(session.id),
            sampled_at=sampled_at,
            viewers=viewers,
            followers=followers,
            title=title,
            category_name=category_name,
            category_id=str(category_id) if category_id is not None else None,
            viewers_source=source,
        )
        .on_conflict_do_nothing(
            index_elements=["stream_id", "sampled_at"],
        )
        .returning(StreamRuntimeSample.id)
    )
    inserted_id = (await db.execute(stmt)).scalar_one_or_none()
    if inserted_id is None:
        return False

    await upsert_bucket(
        db,
        session=session,
        sampled_at=sampled_at,
        viewers=viewers,
        followers=followers,
    )

    session.last_sample_at = sampled_at
    session.samples_count = int(session.samples_count or 0) + 1
    session.updated_at = utcnow()
    await db.flush()
    return True


async def upsert_bucket(
    db: AsyncSession,
    *,
    session: StreamRuntimeSession,
    sampled_at: datetime,
    viewers: int | None,
    followers: int | None,
) -> None:
    bucket_start = _floor_bucket(sampled_at)
    bucket_end = bucket_start + timedelta(minutes=BUCKET_MINUTES)
    stream_id = int(session.stream_id)

    stmt = pg_insert(StreamRuntimeBucket).values(
        stream_id=stream_id,
        stream_session_id=int(session.id),
        bucket_start=bucket_start,
        bucket_end=bucket_end,
        viewers_sum=int(viewers) if viewers is not None else 0,
        sample_count=1 if viewers is not None else 0,
        max_viewers=int(viewers) if viewers is not None else None,
        followers_first=int(followers) if followers is not None else None,
        followers_last=int(followers) if followers is not None else None,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["stream_id", "bucket_start"],
        set_={
            "stream_session_id": stmt.excluded.stream_session_id,
            "bucket_end": stmt.excluded.bucket_end,
            "viewers_sum": StreamRuntimeBucket.viewers_sum
            + stmt.excluded.viewers_sum,
            "sample_count": StreamRuntimeBucket.sample_count
            + stmt.excluded.sample_count,
            "max_viewers": func.greatest(
                StreamRuntimeBucket.max_viewers, stmt.excluded.max_viewers
            ),
            "followers_first": func.coalesce(
                StreamRuntimeBucket.followers_first, stmt.excluded.followers_first
            ),
            "followers_last": func.coalesce(
                stmt.excluded.followers_last, StreamRuntimeBucket.followers_last
            ),
        },
    )
    await db.execute(stmt)

    await db.execute(
        text(
            """
            UPDATE stream_runtime_buckets
            SET avg_viewers = ROUND(
                    viewers_sum::numeric / NULLIF(sample_count, 0)
                )::int,
                followers_gained = CASE
                    WHEN followers_first IS NULL OR followers_last IS NULL
                        THEN NULL
                    ELSE followers_last - followers_first
                END,
                duration_hours = ROUND(
                    EXTRACT(EPOCH FROM (bucket_end - bucket_start)) / 3600.0, 4
                ),
                hours_watched = ROUND(
                    COALESCE(viewers_sum::numeric / NULLIF(sample_count, 0), 0)
                    * EXTRACT(EPOCH FROM (bucket_end - bucket_start)) / 3600.0, 2
                )
            WHERE stream_id = :stream_id AND bucket_start = :bucket_start
            """
        ),
        {"stream_id": stream_id, "bucket_start": bucket_start},
    )
    await db.flush()


async def get_latest_sample_values(
    db: AsyncSession, stream_id: int
) -> tuple[int | None, int | None]:
    """Последние известные viewers/followers — для sample на channel.update."""
    result = await db.execute(
        select(StreamRuntimeSample)
        .where(StreamRuntimeSample.stream_id == stream_id)
        .order_by(StreamRuntimeSample.sampled_at.desc())
        .limit(1)
    )
    sample = result.scalar_one_or_none()
    if sample is None:
        return None, None
    return sample.viewers, sample.followers


# ============================================================
# SESSION SNAPSHOT
# ============================================================


async def load_samples(
    db: AsyncSession, stream_id: int
) -> list[StreamRuntimeSample]:
    result = await db.execute(
        select(StreamRuntimeSample)
        .where(StreamRuntimeSample.stream_id == stream_id)
        .order_by(StreamRuntimeSample.sampled_at)
    )
    return list(result.scalars().all())


def _segments_from_samples(
    samples: list[StreamRuntimeSample], ended_at: datetime | None
) -> list[dict]:
    segments: list[dict] = []
    current_key: str | None = None

    for sample in samples:
        name = sample.category_name
        if not name:
            continue
        key = str(sample.category_id) if sample.category_id else name
        if key == current_key:
            continue
        if segments and segments[-1]["ended_at"] is None:
            segments[-1]["ended_at"] = iso_utc(sample.sampled_at)
        segments.append(
            {
                "category_id": str(sample.category_id) if sample.category_id else None,
                "category_name": name,
                "started_at": iso_utc(sample.sampled_at),
                "ended_at": None,
                "source": sample.viewers_source or "sampling.loop",
            }
        )
        current_key = key

    if segments and segments[-1]["ended_at"] is None:
        segments[-1]["ended_at"] = iso_utc(ended_at)

    return segments


def _histories_from_samples(samples: list[StreamRuntimeSample]) -> tuple[list[dict], list[dict]]:
    title_history: list[dict] = []
    category_history: list[dict] = []
    last_title: str | None = None
    last_category: str | None = None

    for sample in samples:
        if sample.title and sample.title != last_title:
            title_history.append(
                {
                    "title": sample.title,
                    "changed_at": iso_utc(sample.sampled_at),
                    "source": sample.viewers_source or "sampling.loop",
                }
            )
            last_title = sample.title
        if sample.category_name and sample.category_name != last_category:
            category_history.append(
                {
                    "category_id": str(sample.category_id)
                    if sample.category_id
                    else None,
                    "category_name": sample.category_name,
                    "changed_at": iso_utc(sample.sampled_at),
                    "source": sample.viewers_source or "sampling.loop",
                }
            )
            last_category = sample.category_name

    return title_history, category_history


async def build_session_snapshot(
    db: AsyncSession,
    session: StreamRuntimeSession,
    *,
    status: str | None = None,
    ended_at: datetime | None = None,
) -> dict:
    """Собрать dict в форме `StreamSession` из БД.

    Используется `!время`, финализацией и Telegram-хуком. Секунды/микросекунды
    сохраняются из сэмплов, поэтому границы категорий восстанавливаются после
    рестарта процесса.
    """
    stream_result = await db.execute(select(Stream).where(Stream.id == session.stream_id))
    stream = stream_result.scalar_one()

    samples = await load_samples(db, int(session.stream_id))
    effective_ended = to_naive_utc(ended_at) or session.ended_at
    title_history, category_history = _histories_from_samples(samples)
    segments = _segments_from_samples(samples, effective_ended)

    viewer_samples = [
        {
            "viewer_count": int(sample.viewers),
            "sampled_at": iso_utc(sample.sampled_at),
            "source": sample.viewers_source or "sampling.loop",
        }
        for sample in samples
        if sample.viewers is not None
    ]
    follower_samples = [
        {
            "followers_total": int(sample.followers),
            "sampled_at": iso_utc(sample.sampled_at),
            "source": sample.viewers_source or "sampling.loop",
        }
        for sample in samples
        if sample.followers is not None
    ]

    started_at = session.started_at or stream.started_at
    duration_minutes = None
    if started_at and effective_ended and effective_ended > started_at:
        duration_minutes = round(
            (effective_ended - started_at).total_seconds() / 60, 2
        )

    current_title = title_history[-1]["title"] if title_history else stream.title
    current_category = (
        category_history[-1]["category_name"] if category_history else None
    )
    current_category_id = (
        category_history[-1]["category_id"] if category_history else None
    )

    return {
        "version": COLLECTOR_VERSION,
        "status": status or ("active" if session.status == "collecting" else "completed"),
        "channel_login": settings.TWITCH_PRIMARY_CHANNEL,
        "broadcaster_id": str(session.broadcaster_id) if session.broadcaster_id else None,
        "stream_id": session.twitch_stream_id,
        "stream_db_id": int(session.stream_id),
        "session_id": int(session.id),
        "samples_count": int(session.samples_count or 0),
        "last_sample_at": iso_utc(session.last_sample_at),
        "started_at": iso_utc(started_at),
        "ended_at": iso_utc(effective_ended),
        "duration_minutes": duration_minutes,
        "title": stream.title,
        "title_start": title_history[0]["title"] if title_history else stream.title,
        "title_current": current_title,
        "category_name": current_category,
        "category_id": current_category_id,
        "title_history": title_history,
        "category_history": category_history,
        "game_segments": segments,
        "events": [],
        "games_unique": [],
        "games_summary": [],
        "metrics": {
            "sample_interval_seconds": settings.STREAM_RUNTIME_SAMPLE_SECONDS,
            "viewer_samples": viewer_samples,
            "follower_samples": follower_samples,
            "follow_events": [],
            "avg_viewers": None,
            "max_viewers": None,
            "hours_watched": None,
            "viewer_buckets_10m": [],
            "avg_viewers_10m": None,
            "max_viewers_10m": None,
            "hours_watched_10m": None,
            "followers_start": None,
            "followers_end": None,
            "followers_delta": None,
            "followers_delta_exact": None,
            "followers_per_hour_exact": None,
            "tt_compat": {},
        },
        "collector": {
            "created_at": iso_utc(session.created_at or started_at),
            "updated_at": iso_utc(session.updated_at or utcnow()),
            "source": session.finalize_reason or "runtime.collector",
        },
    }


# ============================================================
# FINALIZATION
# ============================================================


async def _resolve_game_for_category(
    db: AsyncSession,
    cache: dict[str, Game],
    *,
    category_id: str | None,
    category_name: str,
) -> Game:
    if category_id:
        result = await db.execute(
            select(Game).where(Game.twitch_category_id == str(category_id)).limit(1)
        )
        game = result.scalar_one_or_none()
        if game is not None:
            cache.setdefault(category_name, game)
            return game

    game = await get_or_create_game(db, cache, category_name, source="stream")
    if category_id and not game.twitch_category_id:
        game.twitch_category_id = str(category_id)
    return game


async def _write_stream_games(
    db: AsyncSession,
    *,
    stream_id: int,
    games_summary: list[dict],
) -> list[int]:
    """Пересобрать `stream_games` из games_summary. Возвращает game_id."""
    await db.execute(delete(StreamGame).where(StreamGame.stream_id == stream_id))

    cache: dict[str, Game] = {}
    game_ids: list[int] = []
    for position, entry in enumerate(games_summary):
        name = (entry.get("category_name") or "").strip()
        if not name:
            continue
        category_id = entry.get("category_id")
        game = await _resolve_game_for_category(
            db, cache, category_id=category_id, category_name=name
        )
        duration = entry.get("duration_minutes")
        db.add(
            StreamGame(
                stream_id=stream_id,
                game_id=int(game.id),
                position=position,
                started_at=_parse_snapshot_dt(entry.get("started_at")),
                ended_at=_parse_snapshot_dt(entry.get("ended_at")),
                duration_minutes=int(round(duration)) if duration is not None else None,
                avg_viewers=_round_int(entry.get("avg_viewers")),
                peak_viewers=entry.get("peak_viewers"),
                followers_gained=entry.get("followers_gained"),
            )
        )
        game_ids.append(int(game.id))

    return game_ids


def _parse_snapshot_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return to_naive_utc(datetime.fromisoformat(value))
    except ValueError:
        return None


def _round_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return None


async def _write_stream_titles(
    db: AsyncSession, *, stream_id: int, snapshot: dict
) -> None:
    existing_result = await db.execute(
        select(StreamTitle.title, StreamTitle.started_at).where(
            StreamTitle.stream_id == stream_id
        )
    )
    existing = {(row[0], row[1]) for row in existing_result.all()}

    for index, item in enumerate(snapshot.get("title_history") or []):
        title = item.get("title")
        started = _parse_snapshot_dt(item.get("changed_at"))
        if not title or started is None or (title, started) in existing:
            continue
        db.add(
            StreamTitle(
                stream_id=stream_id,
                title=title,
                started_at=started,
                is_initial=index == 0,
                created_at=utcnow(),
            )
        )
        existing.add((title, started))


async def enqueue_stats_job(
    db: AsyncSession, session: StreamRuntimeSession
) -> StreamStatsJob:
    now = utcnow()
    check_at = (session.ended_at or now) + timedelta(
        seconds=settings.STREAM_STATS_AGGREGATION_DELAY_SECONDS
    )

    result = await db.execute(
        select(StreamStatsJob).where(
            StreamStatsJob.stream_session_id == int(session.id)
        )
    )
    job = result.scalar_one_or_none()

    if job is None:
        job = StreamStatsJob(
            stream_session_id=int(session.id),
            stream_id=int(session.stream_id),
            check_at=check_at,
            status="pending",
            attempts=0,
            created_at=now,
            updated_at=now,
        )
        db.add(job)
    elif job.status in {"pending", "failed", "cancelled"}:
        job.check_at = check_at
        job.status = "pending"
        job.last_error = None
        job.locked_at = None
        job.locked_by = None
        job.updated_at = now
    elif job.status == "done":
        # Уже агрегирован — повторная постановка не нужна.
        return job

    await db.flush()
    return job


async def mark_session_finalized(
    db: AsyncSession,
    session: StreamRuntimeSession,
    *,
    ended_at: datetime,
    reason: str,
    status: str = "finalized",
) -> StreamStatsJob | None:
    now = utcnow()
    session.status = status
    session.ended_at = to_naive_utc(ended_at)
    session.finalized_at = now
    session.finalize_reason = reason
    session.updated_at = now

    job = None
    if status == "finalized":
        job = await enqueue_stats_job(db, session)
    await db.flush()
    return job


async def finalize_session(
    db: AsyncSession,
    session: StreamRuntimeSession,
    *,
    ended_at: datetime,
    reason: str,
) -> dict:
    """Записать итоги стрима из runtime-сэмплов.

    Возвращает собранный снимок (его же получают finalize-listeners).
    Идемпотентно: `stream_games` пересобираются, `streams` перезаписываются
    значениями из сэмплов.
    """
    from runtime.metrics import recalculate_all_metrics

    last_sample_at = session.last_sample_at
    ended = to_naive_utc(ended_at)
    if last_sample_at is not None and ended < last_sample_at:
        ended = last_sample_at

    snapshot = await build_session_snapshot(
        db, session, status="completed", ended_at=ended
    )
    recalculate_all_metrics(snapshot)

    started = session.started_at
    duration_seconds = (
        (ended - started).total_seconds() if started and ended > started else 0
    )

    if duration_seconds < settings.STREAM_MIN_AGGREGATE_SECONDS:
        await mark_session_finalized(
            db, session, ended_at=ended, reason=reason, status="skipped"
        )
        logger.info(
            "Session %s skipped: duration %.0fs < %ss",
            session.id,
            duration_seconds,
            settings.STREAM_MIN_AGGREGATE_SECONDS,
        )
        return snapshot

    metrics = snapshot["metrics"]
    stream_result = await db.execute(
        select(Stream).where(Stream.id == session.stream_id)
    )
    stream = stream_result.scalar_one()
    stream.ended_at = ended
    stream.duration_minutes = int(round(duration_seconds / 60))
    stream.avg_viewers = _round_int(metrics.get("avg_viewers"))
    stream.max_viewers = metrics.get("max_viewers")
    stream.followers_gained = metrics.get("followers_delta")
    if snapshot.get("title_start"):
        stream.title = snapshot["title_start"]
    stream.updated_at = utcnow()

    await _write_stream_titles(db, stream_id=int(stream.id), snapshot=snapshot)
    game_ids = await _write_stream_games(
        db,
        stream_id=int(stream.id),
        games_summary=snapshot.get("games_summary") or [],
    )
    await mark_session_finalized(db, session, ended_at=ended, reason=reason)

    logger.info(
        "Finalized session %s (stream %s): %s game(s), %s min",
        session.id,
        stream.id,
        len(game_ids),
        stream.duration_minutes,
    )
    return snapshot


async def mark_session_failed(
    db: AsyncSession, session: StreamRuntimeSession, error: str
) -> None:
    session.status = "failed"
    session.finalize_reason = error[:1000]
    session.updated_at = utcnow()
    await db.flush()


def new_worker_id() -> str:
    return f"runtime-stats-{uuid.uuid4().hex[:8]}"
