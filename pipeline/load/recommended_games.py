from __future__ import annotations

"""
Load layer: persistence helpers for RecommendedGame rows.
"""

from collections.abc import Iterable

from sqlalchemy.orm import Session

from database.models import RecommendedGame


def iter_games_missing_short_description(session: Session, *, limit: int = 0) -> Iterable[RecommendedGame]:
    q = session.query(RecommendedGame).filter(RecommendedGame.description_short.is_(None))
    if int(limit) > 0:
        q = q.limit(int(limit))
    return q.all()


def set_game_short_description(session: Session, game: RecommendedGame, description_short: str) -> bool:
    """
    Mutates `game` in-place. Commit/rollback is responsibility of the caller.
    Returns True if the row was changed.
    """
    value = (description_short or "").strip()
    if not value:
        return False
    if (game.description_short or "").strip() == value:
        return False
    game.description_short = value
    session.add(game)
    return True


__all__ = ["iter_games_missing_short_description", "set_game_short_description"]

