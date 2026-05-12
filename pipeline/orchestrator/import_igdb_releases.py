"""
Orchestrates the import of upcoming game releases from IGDB into the recommendations table.
"""

import asyncio
from datetime import datetime

from database.db import SessionLocal
from database.models import RecommendedGame
from pipeline.ingest.igdb_api import ingest_top_upcoming_games
from pipeline.load.load_recommendations import (
    add_igdb_vote,
    create_igdb_recommendation,
)
from pipeline.transform.recommendations_transform import (
    normalize_recommendation_name,
    STATUS_UPCOMING,
)
from utils.logger import get_logger


def import_igdb_releases():
    """
    Fetches top upcoming games from IGDB and loads them as 'IGDB' recommendations.

    This process is idempotent. It checks for existing recommendations by normalized title
    and only inserts new games.
    """
    logger = get_logger("orchestrator.import_igdb_releases")
    session = SessionLocal()

    try:
        logger.info("Starting IGDB upcoming games import...")

        # 1. Ingest: Fetch top upcoming games from IGDB.
        # The API sorts by 'hypes', so we get the most anticipated ones.
        games_meta = asyncio.run(ingest_top_upcoming_games(limit=15))
        if not games_meta:
            logger.info("No upcoming games returned from IGDB.")
            return

        # 2. Load: Check for duplicates and load new games.
        existing_normalized_names = {
            r[0] for r in session.query(RecommendedGame.normalized_name).all()
        }

        added_count = 0
        now = datetime.utcnow()

        for meta in games_meta:
            normalized = normalize_recommendation_name(meta.title)
            if not meta.title or not normalized or normalized in existing_normalized_names:
                continue

            # Create the recommendation record
            recommendation = create_igdb_recommendation(
                session=session,
                normalized_name=normalized,
                title=meta.title,
                status=STATUS_UPCOMING,
                release_date=meta.release_date,
                steam_url=meta.steam_url,
                rating_text=meta.rating_text,
                platforms_text=meta.platforms_text,
                genres_text=meta.genres_text,
                cover_url=meta.cover_url,
                source_name=meta.source_name,
                source_game_id=meta.source_game_id,
                source_payload=meta.source_payload,
                now=now,
            )

            # Add the corresponding 'IGDB' vote
            add_igdb_vote(
                session=session,
                recommended_game_id=recommendation.id,
                now=now,
            )

            existing_normalized_names.add(normalized)
            added_count += 1

        if added_count > 0:
            session.commit()
            logger.info(f"Successfully imported {added_count} new upcoming games from IGDB.")
        else:
            logger.info("No new upcoming games to import from IGDB.")

    except Exception:
        logger.exception("An error occurred during IGDB releases import.")
        session.rollback()
    finally:
        session.close()


if __name__ == "__main__":
    import_igdb_releases()
