from __future__ import annotations

"""
Load layer: writes targeting `streams` table (Stream).
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from database.models import Game, GameMeta, Stream, StreamGame
from pipeline.ingest.twitchtracker_parser import TwitchTrackerStreamRow
from pipeline.load.load_participants import sync_stream_participants_from_title
from pipeline.load.load_stream_games import sync_stream_games
from pipeline.transform.streams_transform import StreamForVodMatch, build_vods_index, is_match, pick_vod_candidates


@dataclass(frozen=True, slots=True)
class SyncStats:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    deleted: int = 0


def sync_streams(
    session: Session,
    streams_data: list[TwitchTrackerStreamRow],
    game_cache: dict[str, Game],
    *,
    prune_missing: bool = False,
    sync_participants_from_title: bool = False,
) -> SyncStats:
    existing_by_external_id: dict[str, Stream] = {
        (stream.external_id or ""): stream
        for stream in session.query(Stream).all()
        if stream.external_id
    }

    # Back-compat: older DBs may not have external_id filled, so also index by date.
    existing_by_date: dict[datetime, Stream] = {
        stream.date: stream
        for stream in session.query(Stream).all()
        if stream.date
    }

    desired_external_ids: set[str] = set()
    stats = SyncStats()

    for data in streams_data:
        external_id = data.date.isoformat()
        desired_external_ids.add(external_id)

        stream = existing_by_external_id.get(external_id) or existing_by_date.get(data.date)
        created = False

        if stream is None:
            stream = Stream()
            session.add(stream)
            session.flush()
            created = True

        changed = created

        if stream.external_id != external_id:
            stream.external_id = external_id
            changed = True

        if stream.date != data.date:
            stream.date = data.date
            changed = True

        for attr, value in (
            ("duration", data.duration_hours),
            ("avg_viewers", data.avg_viewers),
            ("max_viewers", data.max_viewers),
            ("followers", data.followers),
            ("views", data.views),
            ("title", data.title),
        ):
            if getattr(stream, attr) != value:
                setattr(stream, attr, value)
                changed = True

        if sync_stream_games(session, stream, data.games, game_cache):
            changed = True

        if sync_participants_from_title:
            if sync_stream_participants_from_title(session, stream, data.title):
                changed = True

        if created:
            stats = SyncStats(
                added=stats.added + 1,
                updated=stats.updated,
                unchanged=stats.unchanged,
                deleted=stats.deleted,
            )
        elif changed:
            stats = SyncStats(
                added=stats.added,
                updated=stats.updated + 1,
                unchanged=stats.unchanged,
                deleted=stats.deleted,
            )
        else:
            stats = SyncStats(
                added=stats.added,
                updated=stats.updated,
                unchanged=stats.unchanged + 1,
                deleted=stats.deleted,
            )

    if prune_missing:
        deleted = 0
        for stream in session.query(Stream).all():
            if stream.external_id and stream.external_id not in desired_external_ids:
                stream.participants.clear()
                stream.stream_games.clear()
                session.delete(stream)
                deleted += 1

        if deleted:
            stats = SyncStats(
                added=stats.added,
                updated=stats.updated,
                unchanged=stats.unchanged,
                deleted=stats.deleted + deleted,
            )

    return stats


def iter_streams_for_genres(
    session: Session,
    *,
    only_stream_id: int = 0,
    limit: int = 0,
    force: bool = False,
) -> list[Stream]:
    q = session.query(Stream).order_by(Stream.id)

    if int(only_stream_id) > 0:
        q = q.filter(Stream.id == int(only_stream_id))
    elif not force:
        # Also filter pure-whitespace values in orchestrator to avoid sqlite trim edge cases.
        q = q.filter(or_(Stream.genres_text.is_(None), Stream.genres_text == ""))

    q = q.options(
        selectinload(Stream.stream_games).selectinload(StreamGame.game).selectinload(Game.meta),
        selectinload(Stream.participants),
    )

    if int(limit) > 0:
        q = q.limit(int(limit))

    return q.all()


def get_stream_context(stream: Stream) -> tuple[bool, list[str], list[str | None]]:
    has_participants = bool(getattr(stream, "participants", None)) and len(stream.participants) > 0

    game_names: list[str] = []
    game_genres_texts: list[str | None] = []

    for sg in list(getattr(stream, "stream_games", None) or []):
        game = getattr(sg, "game", None)
        if game is None:
            continue

        name = str(getattr(game, "name", "") or "")
        if name:
            game_names.append(name)

        meta = getattr(game, "meta", None)
        if isinstance(meta, GameMeta):
            game_genres_texts.append(getattr(meta, "genres_text", None))
        else:
            game_genres_texts.append(None)

    return has_participants, game_names, game_genres_texts


def set_stream_genres_text(session: Session, stream: Stream, genres_text: str | None) -> bool:
    """
    Mutates stream in-place. Commit/rollback is responsibility of the caller.
    Returns True if changed.
    """
    new_val = None if genres_text is None else str(genres_text)
    old_val = getattr(stream, "genres_text", None)
    if (old_val or "").strip() == (new_val or "").strip():
        return False
    stream.genres_text = new_val
    session.add(stream)
    return True


@dataclass(frozen=True, slots=True)
class VodSyncStats:
    removed_outdated: int
    matched_new: int


def sync_stream_vod_urls(
    session: Session,
    vods: list[dict[str, Any]],
    *,
    only_stream_ids: set[int] | None = None,
) -> VodSyncStats:
    """
    Updates Stream.vod_url in-place:
    - clears stale vod_url values not present in fetched VODs
    - fills missing vod_url values by matching date (+-1 day fallback) and title overlap

    Commit/rollback is responsibility of the caller.
    """
    vod_urls = {str(v.get("url") or "").strip() for v in vods}
    vod_urls.discard("")

    vods_by_date = build_vods_index(vods)

    removed = 0
    streams_with_vods_q = session.query(Stream).filter(Stream.vod_url.isnot(None))
    if only_stream_ids is not None:
        ids = [int(i) for i in only_stream_ids if int(i) > 0]
        if not ids:
            return VodSyncStats(removed_outdated=0, matched_new=0)
        streams_with_vods_q = streams_with_vods_q.filter(Stream.id.in_(ids))
    streams_with_vods = streams_with_vods_q.all()
    for stream in streams_with_vods:
        if stream.vod_url and stream.vod_url not in vod_urls:
            stream.vod_url = None
            removed += 1

    matched = 0
    streams_without_vods_q = session.query(Stream).filter(Stream.vod_url.is_(None))
    if only_stream_ids is not None:
        ids = [int(i) for i in only_stream_ids if int(i) > 0]
        if not ids:
            return VodSyncStats(removed_outdated=removed, matched_new=0)
        streams_without_vods_q = streams_without_vods_q.filter(Stream.id.in_(ids))
    streams_without_vods = streams_without_vods_q.all()
    for stream in streams_without_vods:
        if not stream.date:
            continue

        stream_view = StreamForVodMatch(id=int(stream.id), date=stream.date, title=stream.title)
        candidates = pick_vod_candidates(vods_by_date=vods_by_date, stream_date=stream.date.date())

        for vod in candidates:
            if is_match(stream_view, vod):
                url = str(vod.get("url") or "").strip()
                if url:
                    stream.vod_url = url
                    matched += 1
                break

    return VodSyncStats(removed_outdated=removed, matched_new=matched)


__all__ = [
    "SyncStats",
    "VodSyncStats",
    "get_stream_context",
    "iter_streams_for_genres",
    "set_stream_genres_text",
    "sync_stream_vod_urls",
    "sync_streams",
]

