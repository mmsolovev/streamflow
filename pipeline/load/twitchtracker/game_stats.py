from __future__ import annotations

from sqlalchemy.orm import Session

from database.models import Game, GameStats
from pipeline.ingest.twitchtracker_data import TwitchTrackerGameRow
from pipeline.load.twitchtracker.common import SyncStats
from pipeline.load.twitchtracker.games import get_or_create_game


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


__all__ = ["sync_game_stats"]

