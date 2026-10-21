"""Recommendations query layer — mirrors sheets_recommendations.py without Google Sheets."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    Game,
    GameMetadataIGDB,
    StreamGame,
    User,
    UserProfile,
    game_recommendations,
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
from pipeline.load.load_recommendations import UPCOMING_RELEASE_LOGIN

STATUS_RELEASED = "released"
STATUS_STREAMED = "streamed"


def _twitch_user_ids_subquery():
    """ID псевдопользователя Twitch — его рекомендации в «Советы» не идут."""
    return (
        select(User.id)
        .join(UserProfile, UserProfile.user_id == User.id)
        .where(UserProfile.login == UPCOMING_RELEASE_LOGIN, UserProfile.is_current.is_(True))
        .scalar_subquery()
    )


async def list_recommendations_filter_options(session: AsyncSession) -> dict:
    """Опции фильтров раздела «Советы»: теги и рекомендовавшие."""
    twitch_ids = _twitch_user_ids_subquery()
    subq = (
        select(game_recommendations.c.game_id)
        .where(game_recommendations.c.user_id.notin_(twitch_ids))
        .group_by(game_recommendations.c.game_id)
        .having(func.count() > 0)
    )
    games = select(Game.id.label("id")).where(
        Game.id.in_(subq),
        GameMetadataIGDB.release_date.is_not(None),
        GameMetadataIGDB.release_date <= datetime.utcnow(),
    )
    return await filter_options_for_games(session, games, exclude_twitch=True)


async def list_recommendations(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    query: ListQuery | None = None,
) -> tuple[list[dict], int, int, dict[str, int]]:
    """Советы: поиск, фильтры, сортировка и пагинация выполняются в БД.

    Возвращает `(items, total, total_all, aggregates)`.
    """
    query = query or ListQuery()
    now = datetime.utcnow()
    twitch_ids = _twitch_user_ids_subquery()
    subq = (
        select(game_recommendations.c.game_id)
        .where(game_recommendations.c.user_id.notin_(twitch_ids))
        .group_by(game_recommendations.c.game_id)
        .having(func.count() > 0)
    )
    # Сколько рекомендаций у игры (без псевдопользователя Twitch).
    votes_count = (
        select(func.count())
        .select_from(game_recommendations)
        .where(
            game_recommendations.c.game_id == Game.id,
            game_recommendations.c.user_id.notin_(twitch_ids),
        )
        .scalar_subquery()
    )
    base = (
        select(
            Game.id.label("id"),
            Game.name.label("name"),
            GameMetadataIGDB.release_date.label("release_date"),
            GameMetadataIGDB.steam_url.label("steam_url"),
            GameMetadataIGDB.igdb_score.label("igdb_score"),
            GameMetadataIGDB.cover_url.label("cover_url"),
            GameMetadataIGDB.description_ru.label("description_ru"),
            GameMetadataIGDB.description_en.label("description_en"),
            votes_count.label("votes_count"),
        )
        .join(GameMetadataIGDB, GameMetadataIGDB.game_id == Game.id)
        .where(
            Game.id.in_(subq),
            GameMetadataIGDB.release_date.is_not(None),
            GameMetadataIGDB.release_date <= now,
            # Игры, по которым уже стримили, в «Советы» не показываем.
            ~select(StreamGame.stream_id)
            .where(StreamGame.game_id == Game.id)
            .exists(),
        )
    )
    sq = base.subquery()

    total_all = int(
        (await session.execute(select(func.count()).select_from(sq))).scalar_one() or 0
    )

    q = select(sq)
    condition = query.text_condition((sq.c.name,))
    if condition is not None:
        q = q.where(condition)
    if query.has("steam"):
        q = q.where(sq.c.steam_url.is_not(None))
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
        "title": sq.c.name,
        "igdb": sq.c.igdb_score,
        "votes": sq.c.votes_count,
    }.get(query.sort or "", sq.c.release_date)
    q = q.order_by(
        sort_column.is_(None),
        sort_column.asc() if not query.is_desc else sort_column.desc(),
        sq.c.name.asc(),
    ).offset(offset).limit(limit)

    rows = (await session.execute(q)).all()
    game_ids = [row[0] for row in rows]
    streamed_ids = set()
    if game_ids:
        streamed_result = await session.execute(
            select(StreamGame.game_id)
            .where(StreamGame.game_id.in_(game_ids))
            .distinct()
        )
        streamed_ids = {row[0] for row in streamed_result.all()}

    items = []
    for row in rows:
        (
            game_id,
            name,
            release_date,
            steam_url,
            igdb_score,
            cover_url,
            desc_ru,
            desc_en,
            votes,
        ) = row
        # В списке советов Twitch не показываем — он отмечает ожидаемые новинки.
        recommender_data = [
            entry
            for entry in await game_recommenders(session, game_id)
            if entry.get("user_login") != UPCOMING_RELEASE_LOGIN
        ]
        platforms_text, genres_text = await game_tags(session, game_id)

        status = STATUS_STREAMED if game_id in streamed_ids else STATUS_RELEASED
        items.append(
            {
                "id": game_id,
                "title": name,
                "status": status,
                "release_date": release_date,
                "release_delta_days": release_delta_days(release_date),
                "steam_url": steam_url,
                "igdb_score": igdb_score,
                "cover_url": cover_url,
                "description_ru": desc_ru,
                "description_en": desc_en,
                "votes_count": int(votes or 0),
                "recommenders": build_recommenders_text(recommender_data),
                "recommenders_tooltip": build_recommenders_tooltip(recommender_data),
                "recommenders_list": recommender_data,
                "tags": build_tags_text(platforms_text, genres_text),
            }
        )

    aggregates = await _recommendations_aggregates(session, sq)
    return items, total, total_all, aggregates


async def _recommendations_aggregates(session: AsyncSession, sq) -> dict[str, int]:
    """Числа для шапки раздела «Советы» (по всем советам)."""
    with_score = int(
        (
            await session.execute(
                select(func.count()).select_from(sq).where(sq.c.igdb_score.is_not(None))
            )
        ).scalar_one()
        or 0
    )
    votes = int(
        (
            await session.execute(select(func.coalesce(func.sum(sq.c.votes_count), 0)))
        ).scalar_one()
        or 0
    )
    return {"with_score": with_score, "votes": votes}
