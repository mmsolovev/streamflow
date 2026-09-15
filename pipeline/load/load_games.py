from __future__ import annotations

"""
Load layer: writes targeting `games` table (Game).
"""

from datetime import datetime
from weakref import WeakKeyDictionary

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Game, GameAlias

# Lazy per-session cache of slugs already present in the DB:
# used to generate collision-free slugs within a batch run.
_existing_slugs: WeakKeyDictionary = WeakKeyDictionary()

# Names may only be adopted from authoritative sources (rank >= 2): Twitch
# categories (clips, stream changes, TwitchTracker) beat IGDB. Chat-provided
# names ("manual") never dictate canonical naming. Within a single run a
# higher-ranked source wins over a lower-ranked one for the same game.
SOURCE_RANK = {
    "twitch": 3,
    "twitch_api": 3,
    "twitchtracker": 3,
    "stream": 3,
    "igdb": 2,
    "manual": 1,
}


# Per-session tracker: game_id -> source that last adopted the name.
# Used to keep source priority within a run (Twitch categories > IGDB).
_adopted_sources: WeakKeyDictionary = WeakKeyDictionary()


async def adopt_game_name(
    session: AsyncSession,
    game: Game,
    name: str,
    *,
    source: str = "igdb",
) -> None:
    """Adopt canonical casing (e.g. Twitch category) for an existing game row.

    Only name changes that differ in letter case / whitespace are applied;
    a lower-priority source never overrides a higher-priority one in-run.
    """
    name = (name or "").strip()
    if not name or game.name == name:
        return

    old_name = game.name
    if " ".join(name.casefold().split()) != " ".join(old_name.casefold().split()):
        return

    rank = SOURCE_RANK.get(source, 1)
    adopted = _adopted_sources.get(session)
    if adopted is None:
        adopted = {}
        _adopted_sources[session] = adopted
    if rank < SOURCE_RANK.get(adopted.get(int(game.id)), 1):
        return
    adopted[int(game.id)] = source

    game.name = name
    game.updated_at = datetime.utcnow()

    result = await session.execute(
        select(GameAlias).where(
            GameAlias.game_id == game.id,
            GameAlias.is_primary.is_(True),
        )
    )
    for alias in result.scalars().all():
        if alias.alias.casefold() == old_name.casefold():
            alias.alias = name


async def _load_existing_slugs(session: AsyncSession) -> set[str]:
    slugs = _existing_slugs.get(session)
    if slugs is None:
        result = await session.execute(select(Game.slug))
        slugs = {row[0] for row in result.all() if row[0]}
        _existing_slugs[session] = slugs
    return slugs


async def make_unique_slug(session: AsyncSession, name: str) -> str:
    """Collision-safe slug: reserves a slug not used by any existing game."""
    used = await _load_existing_slugs(session)
    base = name.lower().replace(" ", "-")
    candidate = base
    counter = 2
    while candidate in used:
        candidate = f"{base}-{counter}"
        counter += 1
    used.add(candidate)
    return candidate


async def get_or_create_game(
    session: AsyncSession,
    game_cache: dict[str, Game],
    name: str,
    *,
    source: str = "manual",
) -> Game:
    name = (name or "").strip()
    if not name:
        raise ValueError("Game name is empty")

    game = game_cache.get(name)
    if game is not None:
        return game

    result = await session.execute(select(Game).where(Game.name == name).limit(1))
    game = result.scalar_one_or_none()

    if game is None:
        result = await session.execute(
            select(Game).where(func.lower(Game.name) == name.lower()).order_by(Game.id)
        )
        candidates = list(result.scalars().all())
        if not candidates:
            now = datetime.utcnow()
            slug = await make_unique_slug(session, name)
            game = Game(name=name, slug=slug, created_at=now, updated_at=now)
            session.add(game)
            await session.flush()

            alias = GameAlias(
                game_id=game.id,
                alias=name,
                normalized_alias=name.lower(),
                is_primary=True,
                source=source,
                created_at=now,
            )
            session.add(alias)
            await session.flush()
        else:
            game = candidates[0]
            if SOURCE_RANK.get(source, 1) >= 2:
                await adopt_game_name(session, game, name, source=source)

    game_cache[name] = game
    return game


__all__ = ["adopt_game_name", "get_or_create_game", "make_unique_slug"]
