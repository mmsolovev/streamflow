from __future__ import annotations

"""
Load layer: writes stream-page data to DB (streams, stream_titles,
stream_games per-game metrics, game_stats aggregation).

A stream is identified by Twitch external_id or by its started_at, so
multiple streams on the same calendar day stay separate rows.
"""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Game, Stream, StreamGame, StreamTitle
from pipeline.ingest.twitchtracker_parser import StreamPageData
from pipeline.load.load_games import get_or_create_game
from services import stats_history
from utils.time_utils import tracker_to_utc

_STARTED_AT_TOLERANCE_MINUTES = 30


def _log(message: str) -> None:
    print(message, flush=True)


async def _find_existing_stream(
    session: AsyncSession,
    page: StreamPageData,
    external_id: str | None,
) -> Stream | None:
    """Find the DB stream this page refers to.

    Identity priority (supports several streams per calendar day):
    1. external_id — Twitch stream id resolved from a VOD.
    2. started_at — exact, then nearest within a small tolerance.
    3. Legacy date-only fallback — only when the page has no start time
       and there is exactly one stream on that date.
    """
    if external_id:
        result = await session.execute(
            select(Stream).where(Stream.external_id == external_id)
        )
        stream = result.scalars().first()
        if stream is not None:
            return stream

    if not page.started_at:
        from sqlalchemy import cast, Date

        result = await session.execute(
            select(Stream).where(cast(Stream.started_at, Date) == page.date.date())
        )
        same_day = result.scalars().all()
        if len(same_day) == 1:
            return same_day[0]
        return None

    result = await session.execute(
        select(Stream).where(Stream.started_at == page.started_at)
    )
    stream = result.scalars().first()
    if stream is not None:
        return stream

    tolerance = timedelta(minutes=_STARTED_AT_TOLERANCE_MINUTES)
    result = await session.execute(
        select(Stream).where(
            Stream.started_at.between(
                page.started_at - tolerance,
                page.started_at + tolerance,
            )
        )
    )
    candidates = result.scalars().all()
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        return min(
            candidates,
            key=lambda s: abs((s.started_at - page.started_at).total_seconds()),
        )
    return None


async def upsert_stream_from_page(
    session: AsyncSession,
    page: StreamPageData,
    external_id: str | None,
) -> tuple[Stream, bool]:
    """
    Upsert a Stream from parsed page data.

    Returns (stream, created).
    If external_id is provided and the stream doesn't have one, writes it.
    """
    stream = await _find_existing_stream(session, page, external_id)
    created = False

    if stream is None:
        stream = Stream(
            external_id=external_id,
            started_at=page.started_at,
            ended_at=page.ended_at,
            created_at=datetime.utcnow(),
        )
        session.add(stream)
        await session.flush()
        created = True
        _log(f"  Created stream id={stream.id}, external_id={stream.external_id}")
    else:
        _log(f"  Found existing stream id={stream.id}")

    desired = {
        "external_id": external_id or stream.external_id,
        "started_at": page.started_at,
        "ended_at": page.ended_at,
        "duration_minutes": page.duration_minutes,
        "avg_viewers": page.avg_viewers,
        "max_viewers": page.peak_viewers,
        "followers_gained": page.followers_gained,
        "title": page.title_changes[0].title if page.title_changes else "",
    }
    changes = stats_history.diff_values(stream, desired)
    if changes:
        await stats_history.apply_changes(
            session,
            [
                (stats_history.ENTITY_STREAM, int(stream.id), field, old_value, new_value)
                for field, old_value, new_value in changes
            ],
            source=stats_history.SOURCE_TWITCHTRACKER,
            reason="stream_page",
            stream_id=int(stream.id),
        )
        for field, _old_value, new_value in changes:
            setattr(stream, field, new_value)

    stream.updated_at = datetime.utcnow()

    return stream, created


async def upsert_stream_titles(
    session: AsyncSession,
    stream: Stream,
    page: StreamPageData,
) -> int:
    """Insert new title changes. Returns number of titles added."""
    if not page.title_changes:
        _log("  No title changes parsed")
        return 0

    _log(f"  Processing {len(page.title_changes)} title change(s), stream_id={stream.id}")

    existing_result = await session.execute(
        select(StreamTitle.title, StreamTitle.started_at).where(StreamTitle.stream_id == stream.id)
    )
    existing_titles = {(row[0], row[1]) for row in existing_result.all()}
    _log(f"  Existing titles in DB: {len(existing_titles)}")

    added = 0
    for i, tc in enumerate(page.title_changes):
        title_time = _parse_title_time(tc.time, page.date)
        key = (tc.title, title_time)
        if key in existing_titles:
            _log(f"  Skipping duplicate title: {tc.title[:50]} @ {title_time}")
            continue

        is_initial = (i == 0 and tc.offset is None)
        st = StreamTitle(
            stream_id=stream.id,
            title=tc.title,
            started_at=title_time,
            is_initial=is_initial,
            created_at=datetime.utcnow(),
        )
        session.add(st)
        added += 1
        _log(f"  + Title: {tc.title[:60]} @ {title_time} (initial={is_initial})")

    _log(f"  Titles added this run: {added}")
    return added


def _parse_title_time(time_str: str, base_date: datetime) -> datetime:
    """Parse '12:45' → naive UTC datetime on base_date (время канала)."""
    try:
        parts = time_str.split(":")
        h, m = int(parts[0]), int(parts[1]) if len(parts) > 1 else 0
        local_dt = base_date.replace(hour=h, minute=m, second=0, microsecond=0)
    except (ValueError, IndexError):
        local_dt = base_date
    return tracker_to_utc(local_dt) or local_dt


async def upsert_stream_games_from_page(
    session: AsyncSession,
    stream: Stream,
    page: StreamPageData,
    game_cache: dict[str, Game],
) -> int:
    """
    Update stream_games rows with per-game metrics from page.
    Creates new StreamGame rows if missing. Returns number of rows changed.
    """
    if not page.games:
        return 0

    existing_result = await session.execute(
        select(StreamGame).where(StreamGame.stream_id == stream.id)
    )
    existing_by_game_name = {sg.game.name: sg for sg in existing_result.scalars().all()}

    changed = 0
    for i, entry in enumerate(page.games):
        game = await get_or_create_game(session, game_cache, entry.name, source="twitchtracker")
        sg = existing_by_game_name.get(entry.name)

        if sg is None:
            sg = StreamGame(stream_id=stream.id, game_id=game.id, position=i)
            session.add(sg)
            changed += 1
            _log(f"  + StreamGame: {entry.name} (id={game.id})")
        elif sg.position != i:
            sg.position = i
            changed += 1

        if sg.avg_viewers != entry.avg_viewers:
            sg.avg_viewers = entry.avg_viewers
            changed += 1
        if sg.peak_viewers != entry.peak_viewers:
            sg.peak_viewers = entry.peak_viewers
            changed += 1
        if sg.duration_minutes != entry.duration_minutes:
            sg.duration_minutes = entry.duration_minutes
            changed += 1
        if sg.followers_gained != entry.followers_gained:
            sg.followers_gained = entry.followers_gained
            changed += 1

    return changed


__all__ = [
    "upsert_stream_from_page",
    "upsert_stream_games_from_page",
    "upsert_stream_titles",
]
