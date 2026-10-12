"""Recommendations query layer — mirrors sheets_recommendations.py without Google Sheets."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Game, GameMetadataIGDB, StreamGame, game_recommendations
from backend.repositories._shared import (
    build_recommenders_text,
    build_tags_text,
    game_recommenders,
    game_tags,
    release_delta_days,
)

STATUS_RELEASED = "released"
STATUS_STREAMED = "streamed"


async def list_recommendations(
    session: AsyncSession,
    *,
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
            GameMetadataIGDB.release_date.is_not(None),
            GameMetadataIGDB.release_date <= now,
        )
        .order_by(GameMetadataIGDB.release_date.asc(), Game.name.asc())
    )
    rows = (await session.execute(q)).all()
    total = len(rows)
    page = rows[offset:offset + limit]

    game_ids = [game.id for game, _ in page]
    streamed_ids = set()
    if game_ids:
        streamed_result = await session.execute(
            select(StreamGame.game_id)
            .where(StreamGame.game_id.in_(game_ids))
            .distinct()
        )
        streamed_ids = {row[0] for row in streamed_result.all()}

    items = []
    for game, igdb in page:
        votes_result = await session.execute(
            select(func.count()).where(game_recommendations.c.game_id == game.id)
        )
        votes_count = int(votes_result.scalar_one() or 0)
        recommender_data = await game_recommenders(session, game.id)
        platforms_text, genres_text = await game_tags(session, game.id)

        status = STATUS_STREAMED if game.id in streamed_ids else STATUS_RELEASED
        items.append({
            "id": game.id,
            "title": game.name,
            "status": status,
            "release_date": igdb.release_date,
            "release_delta_days": release_delta_days(igdb.release_date),
            "steam_url": igdb.steam_url,
            "igdb_score": igdb.igdb_score,
            "cover_url": igdb.cover_url,
            "votes_count": votes_count,
            "recommenders": build_recommenders_text(recommender_data),
            "tags": build_tags_text(platforms_text, genres_text),
        })
    return items, total