from __future__ import annotations

"""
Orchestrator to update release dates for upcoming games.
"""

import asyncio

from database.db import SessionLocal
from pipeline.ingest.igdb_api import fetch_games_by_ids
from pipeline.load.load_recommendations import (
    get_upcoming_igdb_games,
    update_release_dates,
)
from pipeline.transform.recommendations_transform import find_games_to_update
from utils.logger import get_logger


def main():
    logger = get_logger("release_dates_updater")
    logger.info("Starting release dates update for upcoming games...")

    session = SessionLocal()
    try:
        # 1. Get upcoming games from our DB
        local_games = get_upcoming_igdb_games(session)
        if not local_games:
            logger.info("No upcoming games found in the database.")
            return

        game_ids = [game.source_game_id for game in local_games]

        # 2. Get actual data from IGDB by game IDs
        igdb_games = asyncio.run(fetch_games_by_ids(game_ids))
        if not igdb_games:
            logger.warning("Could not fetch games from IGDB.")
            return

        # 3. Find games with different release dates
        games_to_update = find_games_to_update(local_games, igdb_games)

        # 4. Update release dates in our DB
        if games_to_update:
            updated_count = update_release_dates(session, games_to_update)
            session.commit()
            logger.info(f"Updated release dates for {updated_count} games.")
        else:
            logger.info("No release dates to update.")

    except Exception:
        logger.exception("An error occurred during release dates update.")
        session.rollback()
    finally:
        session.close()

    logger.info("Release dates update finished.")


if __name__ == "__main__":
    main()
