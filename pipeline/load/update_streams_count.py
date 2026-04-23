from __future__ import annotations

"""
Load helper: recompute denormalized counters in DB.

Currently used to refresh GameStats.streams_count for period='all' based on stream_games.
"""

from sqlalchemy import func
from sqlalchemy.orm import Session

from database.models import GameStats, StreamGame


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

