"""
Orchestrates the import of upcoming game releases from IGDB into recommendations.
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from database.db import AsyncSessionLocal
from database.models import Game
from pipeline.ingest.igdb_api import ingest_top_upcoming_games
from pipeline.load.load_recommendations import (
    create_game_with_igdb,
    add_igdb_note,
    find_game_by_normalized_name,
)
from pipeline.load.load_games import adopt_game_name
from pipeline.load.load_game_meta import link_igdb_genres_and_platforms
from pipeline.transform.recommendations_transform import normalize_recommendation_name
from utils.logger import get_logger


async def _run():
    logger = get_logger("orchestrator.import_igdb_releases")

    logger.info("Starting IGDB upcoming games import...")

    games_meta = await ingest_top_upcoming_games(limit=15)
    if not games_meta:
        logger.info("No upcoming games returned from IGDB.")
        return

    async with AsyncSessionLocal() as session:
        added_count = 0
        updated_count = 0

        for meta in games_meta:
            normalized = normalize_recommendation_name(meta.title)
            if not meta.title or not normalized:
                continue

            existing = await find_game_by_normalized_name(session, normalized)
            if not existing:
                # Fallback: try to find by normalized game name
                res = await session.execute(
                    select(Game).where(Game.name == meta.title)
                )
                existing = res.scalar_one_or_none()
                if not existing:
                    res = await session.execute(
                        select(Game).where(Game.name.ilike(meta.title))
                    )
                    existing = res.scalar_one_or_none()

            if existing:
                try:
                    await adopt_game_name(session, existing, meta.title, source="igdb")
                    updated_count += 1
                    continue
                except Exception as e:
                    logger.warning(f"Failed to adopt name for existing game {existing.name}: {e}")
                    updated_count += 1
                    continue

            try:
                game = await create_game_with_igdb(
                    session,
                    name=meta.title,
                    igdb_id=meta.source_game_id,
                    release_date=meta.release_date,
                    steam_url=meta.steam_url,
                    igdb_score=_parse_igdb_score(meta.rating_text),
                    description_en=meta.description_short,
                    cover_url=meta.cover_url,
                    raw_payload=meta.source_payload,
                )

                # Link genres and platforms from raw payload
                try:
                    import json as _json
                    payload = _json.loads(meta.source_payload) if meta.source_payload else None
                    if payload:
                        await link_igdb_genres_and_platforms(
                            session,
                            game_id=game.id,
                            payload=payload,
                        )
                except Exception as ex:
                    logger.warning(f"Failed to link genres/platforms for {meta.title}: {ex}")

                await add_igdb_note(session, game.id, user_login="igdb")
                added_count += 1
            except IntegrityError as e:
                logger.warning(f"Integrity error creating game '{meta.title}', trying to find existing: {e}")
                await session.rollback()
                # Try to find again after rollback
                existing = await find_game_by_normalized_name(session, normalized)
                if not existing:
                    res = await session.execute(select(Game).where(Game.name == meta.title))
                    existing = res.scalar_one_or_none()
                if existing:
                    try:
                        await adopt_game_name(session, existing, meta.title, source="igdb")
                        updated_count += 1
                    except Exception as ex:
                        logger.warning(f"Failed to adopt after rollback: {ex}")
                        updated_count += 1
                    continue
                else:
                    logger.error(f"Cannot create or find game for '{meta.title}': {e}")
                    continue

        if added_count > 0 or updated_count > 0:
            await session.commit()
            if added_count > 0 and updated_count > 0:
                logger.info(f"Successfully imported {added_count} new upcoming games from IGDB and updated {updated_count} existing ones.")
            elif added_count > 0:
                logger.info(f"Successfully imported {added_count} new upcoming games from IGDB.")
            else:
                logger.info(f"Updated {updated_count} existing upcoming games from IGDB.")
        else:
            logger.info("No new upcoming games to import from IGDB.")


def _parse_igdb_score(rating_text: str | None) -> float | None:
    if not rating_text:
        return None
    import re
    match = re.search(r"(\d+(?:\.\d+)?)", rating_text)
    if match:
        return float(match.group(1))
    return None


def import_igdb_releases():
    asyncio.run(_run())


if __name__ == "__main__":
    import_igdb_releases()
