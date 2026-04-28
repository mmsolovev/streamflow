from __future__ import annotations

from dataclasses import dataclass
import re
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from database.models import Game, GameStats, GameMeta, Participant, Stream, StreamGame
from pipeline.ingest.twitchtracker_data import TwitchTrackerGameRow, TwitchTrackerStreamRow


@dataclass(frozen=True, slots=True)
class SyncStats:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    deleted: int = 0


def unique_in_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        if v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


def extract_participants_from_title(title: str | None) -> list[str]:
    title = title or ""
    # Legacy rule from import_json_to_db.py: @(\w+) -> lower() and unique in order
    return unique_in_order([name.lower() for name in re.findall(r"@(\w+)", title)])


def sync_game_stats(
    session: Session,
    games_data: list[TwitchTrackerGameRow],
    game_cache: dict[str, Game],
    *,
    prune_missing: bool = False,
) -> SyncStats:
    stats = SyncStats()

    desired_game_ids: set[int] = set()

    for data in games_data:
        game = get_or_create_game(session, game_cache, data.name)
        desired_game_ids.add(int(game.id))

        game_stats = session.get(GameStats, {"game_id": game.id, "period": "all"})
        created = False

        if game_stats is None:
            game_stats = GameStats(game_id=game.id, period="all")
            session.add(game_stats)
            created = True

        changed = created

        for attr, value in (
            ("rank", data.rank),
            ("hours_streamed", data.hours_streamed),
            ("avg_viewers", data.avg_viewers),
            ("max_viewers", data.max_viewers),
            ("followers_per_hour", data.followers_per_hour),
            ("last_stream", data.last_stream),
        ):
            if getattr(game_stats, attr) != value:
                setattr(game_stats, attr, value)
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
        for row in session.query(GameStats).filter_by(period="all").all():
            if int(row.game_id) not in desired_game_ids:
                session.delete(row)
                deleted += 1

        if deleted:
            stats = SyncStats(
                added=stats.added,
                updated=stats.updated,
                unchanged=stats.unchanged,
                deleted=stats.deleted + deleted,
            )

    return stats


def get_or_create_game(session: Session, game_cache: dict[str, Game], name: str) -> Game:
    game = game_cache.get(name)
    if game is not None:
        return game

    game = session.query(Game).filter_by(name=name).first()
    if game is None:
        game = Game(name=name)
        session.add(game)
        session.flush()

    # Many parts of the bot assume meta row exists (manual flags etc.).
    if session.query(GameMeta).filter_by(game_id=game.id).first() is None:
        game.meta = GameMeta()

    game_cache[name] = game
    return game


def get_or_create_participant(session: Session, name: str) -> Participant:
    participant = session.query(Participant).filter_by(name=name).first()
    if participant is None:
        participant = Participant(name=name, display_name=f"@{name}")
        session.add(participant)
        session.flush()
    return participant


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


def update_streams_count(session: Session) -> int:
    """
    Recomputes GameStats.streams_count for period='all' from stream_games table.
    Returns number of rows updated.
    """
    counts_by_game_id = dict(
        session.query(StreamGame.game_id, func.count(StreamGame.stream_id))
        .group_by(StreamGame.game_id)
        .all()
    )

    updated = 0
    rows = session.query(GameStats).filter_by(period="all").all()
    for stats in rows:
        new_value = int(counts_by_game_id.get(stats.game_id, 0))
        if int(stats.streams_count or 0) != new_value:
            stats.streams_count = new_value
            updated += 1

    return updated


__all__ = [
    "SyncStats",
    "get_or_create_game",
    "sync_game_stats",
    "sync_stream_games",
    "sync_streams",
    "update_streams_count",
]

