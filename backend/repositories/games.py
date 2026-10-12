"""Games query layer — mirrors sheets_games.py without Google Sheets."""
from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    Game,
    GameMetadataHLTB,
    GameMetadataIGDB,
    GameStats,
    Genre,
    Platform,
    StreamGame,
    game_genres,
    game_platforms,
    streamer_games,
)

_LIGHT_PLATFORMS = {"PC (Microsoft Windows)", "PlayStation 4", "PlayStation 5"}


async def _flags_map(session: AsyncSession, streamer_id: int, game_ids: list[int]) -> dict[int, tuple[bool, bool]]:
    if not game_ids:
        return {}
    result = await session.execute(
        select(streamer_games).where(
            streamer_games.c.streamer_id == streamer_id,
            streamer_games.c.game_id.in_(game_ids),
        )
    )
    return {
        row.game_id: (bool(row.liked), bool(row.completed))
        for row in result.all()
    }


async def _tags_map(session: AsyncSession, game_ids: list[int]) -> dict[int, str]:
    result = {}
    if not game_ids:
        return result
    ids = list(game_ids)

    genres_result = await session.execute(
        select(game_genres.c.game_id, func.coalesce(Genre.abbreviation, Genre.name))
        .join(Genre, Genre.id == game_genres.c.genre_id)
        .where(game_genres.c.game_id.in_(ids))
    )
    genres_by_game: dict[int, list[str]] = {gid: [] for gid in ids}
    for game_id, value in genres_result.all():
        genres_by_game.setdefault(game_id, []).append(value)

    platforms_result = await session.execute(
        select(game_platforms.c.game_id, func.coalesce(Platform.abbreviation, Platform.name))
        .join(Platform, Platform.id == game_platforms.c.platform_id)
        .where(
            game_platforms.c.game_id.in_(ids),
            or_(
                Platform.name.in_(_LIGHT_PLATFORMS),
                Platform.abbreviation.in_({"PC", "PS4", "PS5"}),
            ),
        )
        .order_by(Platform.name)
    )
    platforms_by_game: dict[int, list[str]] = {gid: [] for gid in ids}
    for game_id, value in platforms_result.all():
        platforms_by_game.setdefault(game_id, []).append(value)

    for game_id in ids:
        parts = [
            part for part in [", ".join(platforms_by_game.get(game_id, [])), ", ".join(genres_by_game.get(game_id, []))] if part
        ]
        result[game_id] = " | ".join(parts)
    return result


def _rank_and_order(items: list[dict]) -> list[dict]:
    items.sort(key=lambda r: (-(r["duration_minutes"] or 0), r["name"].casefold()))
    for rank, row in enumerate(items, start=1):
        row["rank"] = rank
    items.sort(
        key=lambda r: (
            r["last_stream"] is None,
            -(r["last_stream"].timestamp()) if r["last_stream"] else 0,
            r["name"].casefold(),
        )
    )
    return items


async def list_games(
    session: AsyncSession,
    *,
    streamer_id: int,
    limit: int,
    offset: int,
) -> tuple[list[dict], int]:
    counts = (
        select(StreamGame.game_id, func.count().label("streams_count"))
        .group_by(StreamGame.game_id)
        .subquery()
    )
    q = (
        select(
            Game,
            GameStats,
            counts.c.streams_count,
            GameMetadataIGDB.steam_url,
            GameMetadataHLTB.hltb_all_styles,
        )
        .join(counts, counts.c.game_id == Game.id)
        .join(GameStats, GameStats.game_id == Game.id)
        .outerjoin(GameMetadataIGDB, GameMetadataIGDB.game_id == Game.id)
        .outerjoin(GameMetadataHLTB, GameMetadataHLTB.game_id == Game.id)
    )
    rows = (await session.execute(q)).all()

    game_ids = [row.Game.id for row in rows]
    flags = await _flags_map(session, streamer_id, game_ids)
    tags_map = await _tags_map(session, game_ids)

    items = []
    for game, stats, streams_count, steam_url, hltb_all in rows:
        liked, completed = flags.get(game.id, (False, False))
        items.append({
            "id": game.id,
            "name": game.name,
            "streams_count": int(streams_count or 0),
            "last_stream": stats.last_stream,
            "duration_minutes": stats.duration_minutes,
            "hltb_all_styles": hltb_all,
            "steam_url": steam_url,
            "liked": liked,
            "completed": completed,
            "tags": tags_map.get(game.id, ""),
        })

    total = len(items)
    _rank_and_order(items)
    return items[offset:offset + limit], total


async def get_game(
    session: AsyncSession,
    game_id: int,
    *,
    streamer_id: int,
) -> dict | None:
    result = await session.execute(
        select(Game, GameStats)
        .outerjoin(GameStats, GameStats.game_id == Game.id)
        .where(Game.id == game_id)
    )
    row = result.first()
    if not row:
        return None
    game, stats = row.Game, row.GameStats

    igdb = (
        await session.execute(
            select(GameMetadataIGDB).where(GameMetadataIGDB.game_id == game.id)
        )
    ).scalar_one_or_none()
    hltb = (
        await session.execute(
            select(GameMetadataHLTB).where(GameMetadataHLTB.game_id == game.id)
        )
    ).scalar_one_or_none()

    flags = await _flags_map(session, streamer_id, [game.id])
    liked, completed = flags.get(game.id, (False, False))
    tags = (await _tags_map(session, [game.id])).get(game.id, "")

    genres = [
        r[0]
        for r in (
            await session.execute(
                select(func.coalesce(Genre.abbreviation, Genre.name))
                .join(game_genres, game_genres.c.genre_id == Genre.id)
                .where(game_genres.c.game_id == game.id)
            )
        ).all()
        if r[0]
    ]
    platforms = [
        r[0]
        for r in (
            await session.execute(
                select(func.coalesce(Platform.abbreviation, Platform.name))
                .join(game_platforms, game_platforms.c.platform_id == Platform.id)
                .where(game_platforms.c.game_id == game.id)
            )
        ).all()
        if r[0]
    ]

    streams_count_row = await session.execute(
        select(func.count()).where(StreamGame.game_id == game.id)
    )

    return {
        "id": game.id,
        "name": game.name,
        "slug": game.slug,
        "game_type": game.game_type,
        "streams_count": int(streams_count_row.scalar_one() or 0),
        "last_stream": stats.last_stream if stats else None,
        "duration_minutes": stats.duration_minutes if stats else 0,
        "hltb_all_styles": hltb.hltb_all_styles if hltb else None,
        "steam_url": igdb.steam_url if igdb else None,
        "liked": liked,
        "completed": completed,
        "tags": tags,
        "genres": genres,
        "platforms": platforms,
    }