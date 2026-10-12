"""Releases query layer — mirrors sheets_releases.py without Google Sheets."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Game, GameMetadataIGDB, game_recommendations, streamer_games
from backend.repositories._shared import (
    build_recommenders_text,
    build_tags_text,
    game_recommenders,
    game_tags,
    release_delta_days,
)


async def list_releases(
    session: AsyncSession,
    *,
    streamer_id: int,
    limit: int,
    offset: int,
) -> tuple[list[dict], int]:
    now = datetime.utcnow()
    subq = (
        select(game_recommendations.c.game_id)
        .group_by(game_recommendations.c.game_id)
        .having(func.count() > 0)
    )
    q = (
        select(Game, GameMetadataIGDB)
        .join(GameMetadataIGDB, GameMetadataIGDB.game_id == Game.id)
        .where(
            Game.id.in_(subq),
            (GameMetadataIGDB.release_date > now) | (GameMetadataIGDB.release_date.is_(None)),
        )
        .order_by(
            GameMetadataIGDB.release_date.is_(None),
            GameMetadataIGDB.release_date.asc(),
            Game.name.asc(),
        )
    )
    rows = (await session.execute(q)).all()
    total = len(rows)
    page = rows[offset:offset + limit]

    items = []
    for game, igdb in page:
        interested_row = await session.execute(
            select(streamer_games.c.interested).where(
                streamer_games.c.game_id == game.id,
                streamer_games.c.streamer_id == streamer_id,
            )
        )
        interested = bool(interested_row.scalar_one_or_none() or False)
        platforms_text, genres_text = await game_tags(session, game.id)
        recommenders = await game_recommenders(session, game.id)

        items.append({
            "id": game.id,
            "name": game.name,
            "release_date": igdb.release_date,
            "release_delta_days": release_delta_days(igdb.release_date),
            "steam_url": igdb.steam_url,
            "description_ru": igdb.description_ru,
            "interested": interested,
            "tags": build_tags_text(platforms_text, genres_text),
            "recommenders": build_recommenders_text(recommenders),
        })
    return items, total