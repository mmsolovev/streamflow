from __future__ import annotations

"""
DB operations for recommendations (RecommendedGame / RecommendedGameVote).

Commit/rollback is responsibility of the caller unless explicitly stated.
"""

from datetime import datetime

from sqlalchemy.orm import Session, joinedload

from database.models import Game, RecommendedGame, RecommendedGameVote
from pipeline.transform.recommendations_transform import (
    STATUS_RELEASED,
    STATUS_STREAMED,
    STATUS_UPCOMING,
    determine_recommendation_status,
    normalize_recommendation_name,
    normalize_user_login,
)


ACTIVE_RECOMMENDATION_STATUSES = {STATUS_UPCOMING, STATUS_RELEASED}


def find_recommendation_by_query(session: Session, query: str) -> RecommendedGame | None:
    normalized_name = normalize_recommendation_name(query)
    if not normalized_name:
        return None

    return (
        session.query(RecommendedGame)
        .options(joinedload(RecommendedGame.votes))
        .filter_by(normalized_name=normalized_name)
        .first()
    )


def add_vote(
    session: Session,
    recommendation: RecommendedGame,
    user_login: str,
    user_display_name: str,
    *,
    created_at: datetime | None = None,
) -> bool:
    normalized_login = normalize_user_login(user_login)
    if not normalized_login:
        raise ValueError("user_login is required")

    existing_vote = (
        session.query(RecommendedGameVote)
        .filter_by(recommended_game_id=recommendation.id, user_login=normalized_login)
        .first()
    )
    if existing_vote:
        return False

    now = created_at or datetime.utcnow()
    vote = RecommendedGameVote(
        recommended_game=recommendation,
        user_login=normalized_login,
        user_display_name=(user_display_name or user_login or "").strip() or normalized_login,
        created_at=now,
    )
    session.add(vote)
    recommendation.updated_at = now
    session.flush()
    return True


def create_recommendation(
    session: Session,
    query_name: str,
    title: str,
    *,
    release_date: datetime | None = None,
    release_precision: str = "unknown",
    description_short: str | None = None,
    steam_url: str | None = None,
    rating_text: str | None = None,
    platforms_text: str | None = None,
    genres_text: str | None = None,
    cover_url: str | None = None,
    source_name: str | None = None,
    source_game_id: str | None = None,
    source_payload: str | None = None,
    status: str | None = None,
) -> RecommendedGame:
    normalized_name = normalize_recommendation_name(title or query_name)
    if not normalized_name:
        raise ValueError("Recommendation query/title is empty")

    now = datetime.utcnow()
    recommendation = RecommendedGame(
        query_name=(query_name or title).strip(),
        normalized_name=normalized_name,
        title=title.strip(),
        status=status or determine_recommendation_status(release_date=release_date),
        release_date=release_date,
        release_precision=release_precision,
        description_short=description_short,
        steam_url=steam_url,
        rating_text=rating_text,
        platforms_text=platforms_text,
        genres_text=genres_text,
        cover_url=cover_url,
        source_name=source_name,
        source_game_id=source_game_id,
        source_payload=source_payload,
        created_at=now,
        updated_at=now,
        last_checked_at=now,
    )
    session.add(recommendation)
    session.flush()
    return recommendation


def _has_special_source(recommendation: RecommendedGame) -> bool:
    for vote in recommendation.votes:
        login = (vote.user_login or "").casefold()
        if login in {"tabula", "igdb"}:
            return True
    return False


def _is_igdb(recommendation: RecommendedGame) -> bool:
    return any((vote.user_login or "").casefold() == "igdb" for vote in recommendation.votes)


def sync_recommendation_matches(session: Session) -> int:
    updated_count = 0

    recommendations = (
        session.query(RecommendedGame)
        .filter(RecommendedGame.status.in_([STATUS_UPCOMING, STATUS_RELEASED, STATUS_STREAMED]))
        .all()
    )

    games_by_name = {
        normalize_recommendation_name(game.name): game
        for game in session.query(Game).all()
        if game.name
    }

    for recommendation in recommendations:
        real_matched_game = games_by_name.get(recommendation.normalized_name)

        if _has_special_source(recommendation):
            matched_game = None
        else:
            matched_game = real_matched_game

        previous_matched_game_id = recommendation.matched_game_id
        previous_status = recommendation.status

        recommendation.matched_game = matched_game

        if _is_igdb(recommendation):
            recommendation.status = STATUS_UPCOMING
        else:
            recommendation.status = determine_recommendation_status(
                release_date=recommendation.release_date,
                matched_game=matched_game,
                streamer_interested=bool(recommendation.streamer_interested),
            )

        if recommendation.matched_game_id != previous_matched_game_id or recommendation.status != previous_status:
            recommendation.updated_at = datetime.utcnow()
            updated_count += 1

    if updated_count:
        session.flush()

    return updated_count


def find_existing_recommendation(
    session: Session,
    *,
    query: str,
    metadata_title: str | None = None,
    source_name: str | None = None,
    source_game_id: str | None = None,
) -> RecommendedGame | None:
    recommendation = find_recommendation_by_query(session, query)
    if recommendation:
        return recommendation

    if metadata_title:
        recommendation = find_recommendation_by_query(session, metadata_title)
        if recommendation:
            return recommendation

    if source_name and source_game_id:
        return (
            session.query(RecommendedGame)
            .options(joinedload(RecommendedGame.votes))
            .filter_by(source_name=source_name, source_game_id=source_game_id)
            .first()
        )

    return None


def find_user_vote_for_recommendation(session: Session, recommendation_id: int, user_login: str) -> RecommendedGameVote | None:
    return (
        session.query(RecommendedGameVote)
        .filter_by(recommended_game_id=recommendation_id, user_login=normalize_user_login(user_login))
        .first()
    )


def load_user_active_votes(session: Session, user_login: str) -> list[RecommendedGameVote]:
    return (
        session.query(RecommendedGameVote)
        .join(RecommendedGame, RecommendedGame.id == RecommendedGameVote.recommended_game_id)
        .options(joinedload(RecommendedGameVote.recommended_game))
        .filter(
            RecommendedGameVote.user_login == normalize_user_login(user_login),
            RecommendedGame.status.in_(ACTIVE_RECOMMENDATION_STATUSES),
        )
        .order_by(RecommendedGameVote.created_at.asc(), RecommendedGameVote.id.asc())
        .all()
    )


def delete_recommendation_if_orphaned(session: Session, recommendation: RecommendedGame) -> bool:
    refreshed = (
        session.query(RecommendedGame)
        .options(joinedload(RecommendedGame.votes))
        .filter_by(id=recommendation.id)
        .first()
    )
    if refreshed and not refreshed.votes:
        session.delete(refreshed)
        session.flush()
        return True
    return False


def remove_vote(session: Session, vote: RecommendedGameVote) -> tuple[str, bool]:
    title = vote.recommended_game.title
    recommendation = vote.recommended_game
    session.delete(vote)
    session.flush()
    deleted_recommendation = delete_recommendation_if_orphaned(session, recommendation)
    return title, deleted_recommendation


__all__ = [
    "ACTIVE_RECOMMENDATION_STATUSES",
    "add_vote",
    "create_recommendation",
    "delete_recommendation_if_orphaned",
    "find_existing_recommendation",
    "find_recommendation_by_query",
    "find_user_vote_for_recommendation",
    "load_user_active_votes",
    "remove_vote",
    "sync_recommendation_matches",
]

