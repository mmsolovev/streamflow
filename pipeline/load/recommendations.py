from __future__ import annotations

"""
Load layer: persistence helpers for RecommendedGame / RecommendedGameVote.
"""

from datetime import datetime

from sqlalchemy.orm import Session

from database.models import RecommendedGame, RecommendedGameVote


def existing_recommendation_titles(session: Session) -> set[str]:
    return {str(r[0]) for r in session.query(RecommendedGame.title).all() if r and r[0]}


def find_recommendation_by_normalized_name(session: Session, normalized_name: str) -> RecommendedGame | None:
    if not normalized_name:
        return None
    return session.query(RecommendedGame).filter_by(normalized_name=normalized_name).first()


def create_igdb_recommendation(
    session: Session,
    *,
    normalized_name: str,
    title: str,
    status: str,
    release_date,
    steam_url: str | None,
    rating_text: str | None,
    platforms_text: str | None,
    genres_text: str | None,
    cover_url: str | None,
    source_name: str | None,
    source_game_id: str | None,
    source_payload: str | None,
    now: datetime,
) -> RecommendedGame:
    rec = RecommendedGame(
        query_name="igdb",
        normalized_name=normalized_name,
        title=title,
        status=status,
        release_date=release_date,
        release_precision="unknown",
        description_short=None,
        steam_url=steam_url,
        rating_text=rating_text,
        platforms_text=platforms_text,
        genres_text=genres_text,
        cover_url=cover_url,
        source_name=source_name,
        source_game_id=source_game_id,
        source_payload=source_payload,
        streamer_interested=False,
        created_at=now,
        updated_at=now,
    )
    session.add(rec)
    session.flush()
    return rec


def add_igdb_vote(session: Session, *, recommended_game_id: int, now: datetime) -> None:
    vote = RecommendedGameVote(
        recommended_game_id=int(recommended_game_id),
        user_login="igdb",
        user_display_name="IGDB",
        created_at=now,
    )
    session.add(vote)


__all__ = [
    "add_igdb_vote",
    "create_igdb_recommendation",
    "existing_recommendation_titles",
    "find_recommendation_by_normalized_name",
]

