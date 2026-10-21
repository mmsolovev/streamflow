"""Releases query layer — mirrors sheets_releases.py without Google Sheets."""
from __future__ import annotations

from datetime import datetime, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    Game,
    GameMetadataIGDB,
    game_recommendations,
    streamer_games,
)
from backend.repositories._shared import (
    build_recommenders_text,
    build_recommenders_tooltip,
    build_tags_text,
    game_recommenders,
    game_tags,
    release_delta_days,
)
from backend.repositories.filters import (
    filter_options_for_games,
    recommender_condition,
    tag_condition,
)
from backend.repositories.list_query import ListQuery

# Сколько последних календарных дней (включая сегодня) считать «недавними».
RECENT_RELEASE_DAYS = 2


async def list_releases_filter_options(session: AsyncSession) -> dict:
    """Опции фильтров раздела «Релизы»: теги и рекомендовавшие."""
    today = datetime.now().date()
    recent_cutoff = datetime.combine(
        today - timedelta(days=RECENT_RELEASE_DAYS - 1), time.min
    )
    subq = (
        select(game_recommendations.c.game_id)
        .group_by(game_recommendations.c.game_id)
        .having(func.count() > 0)
    )
    games = select(Game.id.label("id")).where(
        Game.id.in_(subq),
        (GameMetadataIGDB.release_date >= recent_cutoff)
        | (GameMetadataIGDB.release_date.is_(None)),
    )
    return await filter_options_for_games(session, games)


async def list_releases(
    session: AsyncSession,
    *,
    streamer_id: int,
    limit: int,
    offset: int,
    query: ListQuery | None = None,
) -> tuple[list[dict], int, int, dict[str, int]]:
    """Релизы: поиск, фильтры, сортировка и пагинация выполняются в БД.

    Возвращает `(items, total, total_all, aggregates)`.
    """
    query = query or ListQuery()
    # Релизы показываем начиная с даты выхода за последние RECENT_RELEASE_DAYS
    # календарных дней (включая сегодня) и все будущие. Сравнение по локальной
    # календарной дате: время 00:00 в БД — заглушка, а не реальный момент.
    today = datetime.now().date()
    recent_cutoff = datetime.combine(
        today - timedelta(days=RECENT_RELEASE_DAYS - 1), time.min
    )
    subq = (
        select(game_recommendations.c.game_id)
        .group_by(game_recommendations.c.game_id)
        .having(func.count() > 0)
    )
    # Сколько рекомендаций у игры (для сортировки и подсчёта).
    recommenders_count = (
        select(func.count())
        .select_from(game_recommendations)
        .where(game_recommendations.c.game_id == Game.id)
        .scalar_subquery()
    )
    # Отметка «Интересно» канала — тоже в сортировке.
    interested_flag = (
        select(streamer_games.c.interested)
        .where(
            streamer_games.c.streamer_id == streamer_id,
            streamer_games.c.game_id == Game.id,
        )
        .scalar_subquery()
    )
    base = (
        select(
            Game.id.label("id"),
            Game.name.label("name"),
            GameMetadataIGDB.release_date.label("release_date"),
            GameMetadataIGDB.steam_url.label("steam_url"),
            GameMetadataIGDB.description_ru.label("description_ru"),
            GameMetadataIGDB.description_en.label("description_en"),
            GameMetadataIGDB.cover_url.label("cover_url"),
            recommenders_count.label("recommenders_count"),
            interested_flag.label("interested"),
        )
        .join(GameMetadataIGDB, GameMetadataIGDB.game_id == Game.id)
        .where(
            Game.id.in_(subq),
            (GameMetadataIGDB.release_date >= recent_cutoff)
            | (GameMetadataIGDB.release_date.is_(None)),
        )
    )
    sq = base.subquery()

    total_all = int(
        (await session.execute(select(func.count()).select_from(sq))).scalar_one() or 0
    )

    q = select(sq)
    condition = query.text_condition(
        (sq.c.name, sq.c.description_ru, sq.c.description_en)
    )
    if condition is not None:
        q = q.where(condition)
    if query.has("steam"):
        q = q.where(sq.c.steam_url.is_not(None))
    if query.has("interested"):
        q = q.where(sq.c.interested.is_(True))
    tag_cond = tag_condition(sq.c.id, query.tags)
    if tag_cond is not None:
        q = q.where(tag_cond)
    rec_cond = recommender_condition(sq.c.id, query.recommenders)
    if rec_cond is not None:
        q = q.where(rec_cond)

    total = int(
        (await session.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
        or 0
    )

    sort_column = {
        "release": sq.c.release_date,
        "name": sq.c.name,
        "interested": sq.c.interested,
        "recommenders": sq.c.recommenders_count,
    }.get(query.sort or "", sq.c.release_date)
    q = q.order_by(
        sort_column.is_(None),
        sort_column.asc() if not query.is_desc else sort_column.desc(),
        sq.c.name.asc(),
    ).offset(offset).limit(limit)

    rows = (await session.execute(q)).all()
    items = []
    for row in rows:
        (
            game_id,
            name,
            release_date,
            steam_url,
            desc_ru,
            desc_en,
            cover_url,
            rec_count,
            interested,
        ) = row
        platforms_text, genres_text = await game_tags(session, game_id)
        recommenders = await game_recommenders(session, game_id)

        items.append(
            {
                "id": game_id,
                "name": name,
                "release_date": release_date,
                "release_delta_days": release_delta_days(release_date),
                "steam_url": steam_url,
                "description_ru": desc_ru,
                "description_en": desc_en,
                "cover_url": cover_url,
                "interested": bool(interested or False),
                "tags": build_tags_text(platforms_text, genres_text),
                "recommenders": build_recommenders_text(recommenders),
                "recommenders_tooltip": build_recommenders_tooltip(recommenders),
                "recommenders_list": recommenders,
                "recommenders_count": int(rec_count or 0),
            }
        )

    aggregates = await _releases_aggregates(session, sq)
    return items, total, total_all, aggregates


async def _releases_aggregates(session: AsyncSession, sq) -> dict[str, int]:
    """Числа для шапки раздела «Релизы» (по всем релизам)."""
    interested = int(
        (
            await session.execute(
                select(func.count()).select_from(sq).where(sq.c.interested.is_(True))
            )
        ).scalar_one()
        or 0
    )
    released = int(
        (
            await session.execute(
                select(func.count())
                .select_from(sq)
                .where(
                    sq.c.release_date.is_not(None),
                    sq.c.release_date <= datetime.utcnow(),
                )
            )
        ).scalar_one()
        or 0
    )
    return {"interested": interested, "released": released}
