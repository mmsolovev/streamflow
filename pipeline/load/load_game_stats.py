from __future__ import annotations

"""
Load layer: writes targeting `games_stats` table (GameStats).
"""

from dataclasses import dataclass

from sqlalchemy import func
from sqlalchemy.orm import Session

from database.models import Game, GameStats, StreamGame
from pipeline.ingest.twitchtracker_parser import TwitchTrackerGameRow
from pipeline.load.load_games import get_or_create_game


@dataclass(frozen=True, slots=True)
class SyncStats:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    deleted: int = 0


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


__all__ = ["SyncStats", "sync_game_stats", "update_streams_count"]

