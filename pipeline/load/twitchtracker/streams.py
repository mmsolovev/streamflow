from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from database.models import Game, Stream, StreamGame
from pipeline.ingest.twitchtracker_data import TwitchTrackerStreamRow
from pipeline.load.twitchtracker.common import SyncStats, extract_participants_from_title, unique_in_order
from pipeline.load.twitchtracker.games import get_or_create_game, get_or_create_participant


def _sync_stream_participants_from_title(session: Session, stream: Stream, title: str | None) -> bool:
    desired_names = extract_participants_from_title(title)
    desired_set = set(desired_names)
    changed = False

    existing_by_name = {p.name: p for p in stream.participants}
    for name, participant in list(existing_by_name.items()):
        if name not in desired_set:
            stream.participants.remove(participant)
            changed = True

    existing_names = {p.name for p in stream.participants}
    for name in desired_names:
        if name in existing_names:
            continue
        stream.participants.append(get_or_create_participant(session, name))
        existing_names.add(name)
        changed = True

    return changed


def sync_stream_games(session: Session, stream: Stream, game_names: list[str], game_cache: dict[str, Game]) -> bool:
    """
    Ensures Stream.stream_games match the given ordered list of names.
    Returns True if association changed.
    """
    desired_names = unique_in_order([n for n in game_names if n])
    desired_set = set(desired_names)
    changed = False

    existing_by_name = {sg.game.name: sg for sg in stream.stream_games}

    # Remove missing.
    for game_name, stream_game in list(existing_by_name.items()):
        if game_name not in desired_set:
            stream.stream_games.remove(stream_game)
            changed = True

    # Rebuild map after removals.
    existing_by_name = {sg.game.name: sg for sg in stream.stream_games}

    # Upsert with correct positions.
    for position, game_name in enumerate(desired_names):
        game = get_or_create_game(session, game_cache, game_name)
        stream_game = existing_by_name.get(game_name)
        if stream_game is None:
            stream.stream_games.append(StreamGame(game=game, position=position))
            changed = True
        elif stream_game.position != position:
            stream_game.position = position
            changed = True

    return changed


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
            if _sync_stream_participants_from_title(session, stream, data.title):
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


__all__ = [
    "sync_stream_games",
    "sync_streams",
]
