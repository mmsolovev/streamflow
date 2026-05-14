from __future__ import annotations

"""
Load layer: writes targeting `recommended_games` and related tables (RecommendedGame, RecommendedGameVote).

This module is the single entry-point for recommendations persistence.
"""

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy.orm import Session, joinedload

from database.models import Game, RecommendedGame, RecommendedGameVote
from pipeline.transform.recommendations_transform import (
    STATUS_RELEASED,
    STATUS_STREAMED,
    STATUS_UPCOMING,
    STATUS_DELETABLE_IGDB,
    determine_recommendation_status,
    normalize_recommendation_name,
    normalize_user_login,
)
from pipeline.transform.sheets_transform import normalize_row, parse_sheet_bool


ACTIVE_RECOMMENDATION_STATUSES = {STATUS_UPCOMING, STATUS_RELEASED}


def existing_recommendation_titles(session: Session) -> set[str]:
    return {str(r[0]) for r in session.query(RecommendedGame.title).all() if r and r[0]}


def find_recommendation_by_normalized_name(session: Session, normalized_name: str) -> RecommendedGame | None:
    if not normalized_name:
        return None
    return session.query(RecommendedGame).filter_by(normalized_name=normalized_name).first()


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
        status=status or determine_recommendation_status(release_date=release_date, source_name=source_name),
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


def _get_source_votes(recommendation: RecommendedGame, source_name: str) -> list[RecommendedGameVote]:
    return [vote for vote in recommendation.votes if (vote.user_login or "").casefold() == source_name.casefold()]

def _get_dominant_source(recommendation: RecommendedGame) -> str | None:
    has_igdb_vote = any((v.user_login or "").casefold() == "igdb" for v in recommendation.votes)
    if has_igdb_vote:
        return "igdb"
    
    has_tabula_vote = any((v.user_login or "").casefold() == "tabula" for v in recommendation.votes)
    if has_tabula_vote:
        return "tabula"
        
    return None

def sync_recommendation_matches(session: Session) -> int:
    updated_count = 0

    recommendations = (
        session.query(RecommendedGame)
        .options(joinedload(RecommendedGame.votes))
        .filter(RecommendedGame.status.in_([STATUS_UPCOMING, STATUS_RELEASED, STATUS_STREAMED, STATUS_DELETABLE_IGDB]))
        .all()
    )

    games_by_name = {
        normalize_recommendation_name(game.name): game
        for game in session.query(Game).all()
        if game.name
    }

    for recommendation in recommendations:
        original_status = recommendation.status
        changed = False

        # --- Deletion Phase ---
        # First, check if an IGDB vote should be deleted without changing the status yet.
        source_for_deletion_check = _get_dominant_source(recommendation)
        status_for_deletion_check = determine_recommendation_status(
            release_date=recommendation.release_date,
            matched_game=None,  # Check for deletion independently of streamed status
            streamer_interested=bool(recommendation.streamer_interested),
            source_name=source_for_deletion_check,
        )

        if status_for_deletion_check == STATUS_DELETABLE_IGDB and source_for_deletion_check == "igdb":
            igdb_votes = _get_source_votes(recommendation, "igdb")
            if igdb_votes and len(recommendation.votes) == len(igdb_votes):
                session.delete(recommendation)
                updated_count += 1
                continue  # Skip to the next recommendation as this one is gone
            elif igdb_votes:
                for vote in igdb_votes:
                    session.delete(vote)
                # The recommendation object in memory now has its `votes` collection updated.
                # We can now proceed to re-evaluate its status based on remaining votes.
                changed = True

        # --- Status Update Phase ---
        # Now, determine the final status based on the *current* state of votes.
        final_source_name = _get_dominant_source(recommendation)
        
        if final_source_name:
            matched_game = None
        else:
            matched_game = games_by_name.get(recommendation.normalized_name)
        
        recommendation.matched_game = matched_game

        final_status = determine_recommendation_status(
            release_date=recommendation.release_date,
            matched_game=matched_game,
            streamer_interested=bool(recommendation.streamer_interested),
            source_name=final_source_name,
        )

        if original_status != final_status:
            recommendation.status = final_status
            changed = True

        if changed:
            recommendation.updated_at = datetime.utcnow()
            updated_count += 1

    if updated_count > 0:
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


def apply_releases_manual_fields(session: Session, rows_by_title: dict[str, list], width: int = 12) -> int:
    """
    Updates manual fields from Sheets targeting `recommended_games`.
    Commit/rollback is responsibility of the caller.
    """
    updated = 0

    for title, row in (rows_by_title or {}).items():
        recommendation = session.query(RecommendedGame).filter_by(title=title).first()
        if not recommendation:
            continue

        normalized = normalize_row(row, width)
        sheet_value = parse_sheet_bool(normalized[5])

        # Preserve previous semantics from legacy sync:
        # - TRUE always sets streamer_interested=True
        # - FALSE does not override True once it's set
        if sheet_value is True and recommendation.streamer_interested is not True:
            recommendation.streamer_interested = True
            updated += 1
        elif sheet_value is False and recommendation.streamer_interested is False:
            recommendation.streamer_interested = False

    session.flush()
    return updated


def get_upcoming_igdb_games(session: Session) -> list[RecommendedGame]:
    """
    Returns all upcoming games that were sourced from IGDB and have a source_game_id.
    """
    return (
        session.query(RecommendedGame)
        .filter(
            RecommendedGame.status == STATUS_UPCOMING,
            RecommendedGame.source_name == "igdb",
            RecommendedGame.source_game_id.isnot(None),
        )
        .all()
    )


def update_release_dates(session: Session, games_to_update: list[RecommendedGame]) -> int:
    """
    Updates the release_date for a list of games.
    """
    if not games_to_update:
        return 0

    now = datetime.utcnow()
    for game in games_to_update:
        game.updated_at = now
        session.add(game)

    session.flush()
    return len(games_to_update)


__all__ = [
    "ACTIVE_RECOMMENDATION_STATUSES",
    "STATUS_RELEASED",
    "STATUS_STREAMED",
    "STATUS_UPCOMING",
    "add_igdb_vote",
    "add_vote",
    "apply_releases_manual_fields",
    "create_igdb_recommendation",
    "create_recommendation",
    "delete_recommendation_if_orphaned",
    "existing_recommendation_titles",
    "find_existing_recommendation",
    "find_recommendation_by_normalized_name",
    "find_recommendation_by_query",
    "find_user_vote_for_recommendation",
    "get_upcoming_igdb_games",
    "iter_games_missing_short_description",
    "load_user_active_votes",
    "remove_vote",
    "set_game_short_description",
    "sync_recommendation_matches",
    "update_release_dates",
]