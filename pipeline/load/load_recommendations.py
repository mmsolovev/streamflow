from __future__ import annotations

"""
Load layer: writes targeting `games`, `game_metadata_igdb`, `game_recommendations`,
`streamer_games` tables — replaces old RecommendedGame / RecommendedGameVote.
"""

from datetime import datetime

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import (
    Game,
    GameMetadataIGDB,
    GameAlias,
    game_recommendations,
    streamer_games,
)
from pipeline.load.load_game_meta import link_igdb_genres_and_platforms
from pipeline.load.load_games import make_unique_slug
from pipeline.transform.recommendations_transform import normalize_recommendation_name, normalize_user_login
from services.user_service import get_or_create_user_by_login


ACTIVE_RECOMMENDATION_STATUSES = {"upcoming", "released"}

# Псевдо-пользователь «Twitch»: отметка игр, которые IGDB считает ожидаемыми новинками.
# Ставится только скриптом import_igdb_releases.py.
UPCOMING_RELEASE_LOGIN = "twitch"
UPCOMING_RELEASE_NOTE = "Ожидаемая новинка по версии Twitch"


async def existing_recommendation_titles(session: AsyncSession) -> set[str]:
    result = await session.execute(select(Game.name))
    return {str(r[0]) for r in result.all() if r and r[0]}


async def find_game_by_normalized_name(session: AsyncSession, normalized_name: str) -> Game | None:
    if not normalized_name:
        return None
    result = await session.execute(
        select(Game).join(GameAlias, GameAlias.game_id == Game.id)
        .where(GameAlias.normalized_alias == normalized_name)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def find_game_by_query(session: AsyncSession, query: str) -> Game | None:
    normalized = normalize_recommendation_name(query)
    if not normalized:
        return None
    result = await session.execute(
        select(Game).join(GameAlias, GameAlias.game_id == Game.id)
        .where(GameAlias.normalized_alias == normalized)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def find_game_with_igdb(session: AsyncSession, normalized_name: str) -> Game | None:
    if not normalized_name:
        return None
    result = await session.execute(
        select(Game)
        .options(selectinload(Game.igdb_metadata))
        .join(GameAlias, GameAlias.game_id == Game.id)
        .where(GameAlias.normalized_alias == normalized_name)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def add_recommendation(
    session: AsyncSession,
    game: Game,
    user_login: str,
    *,
    note: str | None = None,
) -> bool:
    normalized_login = normalize_user_login(user_login)
    if not normalized_login:
        raise ValueError("user_login is required")

    user = await get_or_create_user_by_login(session, normalized_login)

    existing = await session.execute(
        select(game_recommendations).where(
            game_recommendations.c.user_id == user.id,
            game_recommendations.c.game_id == game.id,
        )
    )
    if existing.first():
        return False

    await session.execute(
        game_recommendations.insert().values(
            user_id=user.id,
            game_id=game.id,
            recommendation_note=note,
            created_at=datetime.utcnow(),
        )
    )
    await session.flush()
    return True


async def create_game(
    session: AsyncSession,
    name: str,
    *,
    slug: str | None = None,
) -> Game:
    normalized = normalize_recommendation_name(name)
    if not normalized:
        raise ValueError("Game name is empty")

    now = datetime.utcnow()
    if not slug:
        slug = await make_unique_slug(session, name)

    game = Game(name=name.strip(), slug=slug, created_at=now, updated_at=now)
    session.add(game)
    await session.flush()

    alias = GameAlias(
        game_id=game.id,
        alias=name.strip(),
        normalized_alias=normalized,
        is_primary=True,
        source="manual",
        created_at=now,
    )
    session.add(alias)
    await session.flush()
    return game


async def create_game_with_igdb(
    session: AsyncSession,
    *,
    name: str,
    igdb_id: str | None = None,
    release_date: datetime | None = None,
    steam_url: str | None = None,
    igdb_score: float | None = None,
    description_en: str | None = None,
    description_ru: str | None = None,
    cover_url: str | None = None,
    raw_payload: str | None = None,
) -> Game:
    normalized = normalize_recommendation_name(name)
    if not normalized:
        raise ValueError("Game name is empty")

    now = datetime.utcnow()
    slug = await make_unique_slug(session, name)

    game = Game(name=name.strip(), slug=slug, created_at=now, updated_at=now)
    session.add(game)
    await session.flush()

    alias = GameAlias(
        game_id=game.id,
        alias=name.strip(),
        normalized_alias=normalized,
        is_primary=True,
        source="igdb",
        created_at=now,
    )
    session.add(alias)

    import json as _json
    # Round igdb_score to one decimal place if provided
    rounded_score = None
    if igdb_score is not None:
        try:
            rounded_score = round(float(igdb_score), 1)
        except (TypeError, ValueError):
            rounded_score = None

    igdb_meta = GameMetadataIGDB(
        game_id=game.id,
        igdb_id=igdb_id or f"pending-{game.id}",
        release_date=release_date,
        steam_url=steam_url,
        igdb_score=rounded_score,
        igdb_name=name,
        description_en=description_en,
        description_ru=description_ru,
        cover_url=cover_url,
        raw_payload=_json.loads(raw_payload) if raw_payload else None,
        synced_at=now,
    )
    session.add(igdb_meta)
    await session.flush()

    # Теги (жанры/платформы) для списков — из того же IGDB-payload, что и метаданные.
    if isinstance(igdb_meta.raw_payload, dict):
        await link_igdb_genres_and_platforms(session, game_id=game.id, payload=igdb_meta.raw_payload)

    return game


async def add_upcoming_release_note(
    session: AsyncSession,
    game_id: int,
    *,
    user_login: str = UPCOMING_RELEASE_LOGIN,
    note: str = UPCOMING_RELEASE_NOTE,
) -> None:
    """Отметка «ожидаемая новинка по версии Twitch» (только import_igdb_releases.py)."""
    user = await get_or_create_user_by_login(session, user_login)
    existing = await session.execute(
        select(game_recommendations).where(
            game_recommendations.c.user_id == user.id,
            game_recommendations.c.game_id == game_id,
        )
    )
    if not existing.first():
        await session.execute(
            game_recommendations.insert().values(
                user_id=user.id,
                game_id=game_id,
                recommendation_note=note,
                created_at=datetime.utcnow(),
            )
        )
        await session.flush()


async def set_release_interest_recommendation(
    session: AsyncSession,
    game_id: int,
    *,
    user_login: str,
    note: str,
    interested: bool,
) -> bool:
    """Синхронизирует рекомендацию канала с отметкой «Интересно».

    * ``interested=True`` — создаёт рекомендацию пользователя ``user_login`` с
      пометкой ``note`` (если её ещё нет). Уже существующая рекомендация не
      трогается: чужой комментарий не перезаписывается, а пустой — дополняется.
    * ``interested=False`` — удаляет только ту рекомендацию, у которой заметка
      совпадает с ``note`` (то есть созданную этой механикой).

    Возвращает ``True``, если база изменилась.
    """
    user = await get_or_create_user_by_login(session, normalize_user_login(user_login))
    result = await session.execute(
        select(game_recommendations).where(
            game_recommendations.c.user_id == user.id,
            game_recommendations.c.game_id == game_id,
        )
    )
    row = result.first()

    if interested:
        if row is None:
            await session.execute(
                game_recommendations.insert().values(
                    user_id=user.id,
                    game_id=game_id,
                    recommendation_note=note,
                    created_at=datetime.utcnow(),
                )
            )
            await session.flush()
            return True
        existing_note = row.recommendation_note if hasattr(row, "recommendation_note") else None
        if not existing_note:
            await session.execute(
                game_recommendations.update()
                .where(
                    game_recommendations.c.user_id == user.id,
                    game_recommendations.c.game_id == game_id,
                )
                .values(recommendation_note=note)
            )
            await session.flush()
            return True
        return False

    if row is None:
        return False
    existing_note = row.recommendation_note if hasattr(row, "recommendation_note") else None
    if existing_note != note:
        return False
    await session.execute(
        delete(game_recommendations).where(
            game_recommendations.c.user_id == user.id,
            game_recommendations.c.game_id == game_id,
        )
    )
    await session.flush()
    return True


async def find_existing_game(
    session: AsyncSession,
    *,
    query: str,
    metadata_title: str | None = None,
) -> Game | None:
    game = await find_game_by_query(session, query)
    if game:
        return game
    if metadata_title:
        game = await find_game_by_query(session, metadata_title)
        if game:
            return game
    return None


async def find_user_recommendation(session: AsyncSession, game_id: int, user_login: str) -> dict | None:
    user = await get_or_create_user_by_login(session, normalize_user_login(user_login))
    result = await session.execute(
        select(game_recommendations).where(
            game_recommendations.c.user_id == user.id,
            game_recommendations.c.game_id == game_id,
        )
    )
    row = result.first()
    return dict(row._mapping) if row else None


async def load_user_recommendations(session: AsyncSession, user_login: str) -> list[dict]:
    user = await get_or_create_user_by_login(session, normalize_user_login(user_login))
    result = await session.execute(
        select(game_recommendations, Game)
        .join(Game, Game.id == game_recommendations.c.game_id)
        .where(game_recommendations.c.user_id == user.id)
        .order_by(game_recommendations.c.created_at.asc())
    )
    return [dict(row._mapping) for row in result.all()]


async def remove_recommendation(session: AsyncSession, user_id: int, game_id: int) -> None:
    """Снять рекомендацию пользователя. Игра при этом остаётся в БД."""
    await session.execute(
        delete(game_recommendations).where(
            game_recommendations.c.user_id == user_id,
            game_recommendations.c.game_id == game_id,
        )
    )
    await session.flush()


async def iter_games_missing_short_description(session: AsyncSession, *, limit: int = 0) -> list[Game]:
    q = (
        select(Game)
        .outerjoin(GameMetadataIGDB, Game.id == GameMetadataIGDB.game_id)
        .where(
            (GameMetadataIGDB.description_ru.is_(None)) | (GameMetadataIGDB.description_ru == "")
        )
    )
    if int(limit) > 0:
        q = q.limit(int(limit))
    result = await session.execute(q)
    return list(result.scalars().all())


async def set_game_short_description(session: AsyncSession, game: Game, description_short: str) -> bool:
    value = (description_short or "").strip()
    if not value:
        return False

    result = await session.execute(select(GameMetadataIGDB).where(GameMetadataIGDB.game_id == game.id))
    meta = result.scalar_one_or_none()
    if meta is None:
        return False
    if (meta.description_ru or "").strip() == value:
        return False
    meta.description_ru = value
    session.add(meta)
    return True


async def set_streamer_interested(session: AsyncSession, game_id: int, user_login: str, interested: bool) -> bool:
    user = await get_or_create_user_by_login(session, normalize_user_login(user_login))
    result = await session.execute(
        select(streamer_games).where(
            streamer_games.c.streamer_id == user.id,
            streamer_games.c.game_id == game_id,
        )
    )
    row = result.first()
    if row is None:
        await session.execute(
            streamer_games.insert().values(
                streamer_id=user.id, game_id=game_id, interested=interested,
                updated_at=datetime.utcnow(),
            )
        )
        await session.flush()
        return True
    if bool(row.interested) != interested:
        await session.execute(
            streamer_games.update()
            .where(
                streamer_games.c.streamer_id == user.id,
                streamer_games.c.game_id == game_id,
            )
            .values(interested=interested, updated_at=datetime.utcnow())
        )
        await session.flush()
        return True
    return False


async def get_upcoming_games(session: AsyncSession) -> list[Game]:
    result = await session.execute(
        select(Game)
        .options(selectinload(Game.igdb_metadata))
        .join(GameMetadataIGDB, Game.id == GameMetadataIGDB.game_id)
        .where(GameMetadataIGDB.release_date > datetime.utcnow())
    )
    return list(result.scalars().all())


async def update_release_dates(session: AsyncSession, games_to_update: list[Game]) -> int:
    if not games_to_update:
        return 0
    now = datetime.utcnow()
    for game in games_to_update:
        game.updated_at = now
        session.add(game)
    await session.flush()
    return len(games_to_update)


__all__ = [
    "ACTIVE_RECOMMENDATION_STATUSES",
    "UPCOMING_RELEASE_LOGIN",
    "UPCOMING_RELEASE_NOTE",
    "add_recommendation",
    "add_upcoming_release_note",
    "create_game",
    "create_game_with_igdb",
    "existing_recommendation_titles",
    "find_existing_game",
    "find_game_by_normalized_name",
    "find_game_by_query",
    "find_game_with_igdb",
    "find_user_recommendation",
    "get_upcoming_games",
    "iter_games_missing_short_description",
    "load_user_recommendations",
    "remove_recommendation",
    "set_game_short_description",
    "set_streamer_interested",
    "update_release_dates",
]
