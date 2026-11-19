"""Resolve runtime Twitch categories and enrich games with IGDB metadata."""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone

from sqlalchemy import func, select

from database.db import AsyncSessionLocal
from database.models import (
    Game,
    GameAlias,
    GameMetadataIGDB,
    GameTwitchCategory,
)
from pipeline.ingest.igdb_api import (
    RecommendationMetadata,
    fetch_igdb_metadata,
    fetch_igdb_metadata_by_id,
)
from pipeline.load.load_games import make_unique_slug
from pipeline.load.load_game_meta import apply_igdb_patch
from services import twitch_service
from utils.logger import get_logger

logger = get_logger("games.metadata")

_NON_IGDB_CATEGORIES = {
    "art",
    "beach",
    "dance",
    "fitness",
    "food and drink",
    "hot tub",
    "irl",
    "just chatting",
    "mukbang",
    "music",
    "outdoors",
    "pools",
    "science and technology",
    "talk shows",
    "travel",
    "asmr",
}


def normalize_category_name(value: str | None) -> str:
    value = unicodedata.normalize("NFKC", value or "").casefold()
    value = value.replace("&", " and ")
    value = re.sub(r"[^\w\s]", " ", value)
    return " ".join(value.split())


def is_non_igdb_category(name: str | None) -> bool:
    return normalize_category_name(name) in _NON_IGDB_CATEGORIES


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _metadata_patch(meta: RecommendationMetadata) -> dict:
    return {
        "igdb_id": str(meta.source_game_id),
        "igdb_name": meta.title,
        "release_date": meta.release_date,
        "steam_url": meta.steam_url,
        "description_en": meta.description_short,
        "cover_url": meta.cover_url,
        "raw_payload": meta.source_payload,
        "synced_at": _utcnow(),
    }


async def _fetch_igdb_metadata(
    *,
    igdb_id: str | None,
    category_name: str,
    non_game: bool,
) -> RecommendationMetadata | None:
    if non_game:
        return None
    if igdb_id:
        try:
            return await fetch_igdb_metadata_by_id(igdb_id)
        except Exception:
            logger.exception("IGDB lookup by Twitch-provided igdb_id=%s failed", igdb_id)
            return None
    if not category_name:
        return None
    try:
        return await fetch_igdb_metadata(category_name)
    except Exception:
        logger.exception("IGDB name fallback failed for Twitch category %r", category_name)
        return None


async def _find_name_candidates(db, name: str) -> list[Game]:
    normalized = normalize_category_name(name)
    if not normalized:
        return []
    lower_name = " ".join((name or "").casefold().split())
    result = await db.execute(
        select(Game)
        .outerjoin(GameAlias, GameAlias.game_id == Game.id)
        .where(
            (func.lower(Game.name) == lower_name)
            | (func.lower(GameAlias.alias) == lower_name)
            | (GameAlias.normalized_alias == normalized)
        )
        .distinct()
        .order_by(Game.id)
    )
    return result.scalars().all()


async def _create_category_game(
    db,
    *,
    category_id: str | None,
    category_name: str,
    igdb_meta: RecommendationMetadata | None,
) -> Game:
    preferred_name = category_name.strip() or (igdb_meta.title if igdb_meta else "")
    if not preferred_name:
        preferred_name = f"Twitch category {category_id or 'unknown'}"

    result = await db.execute(select(Game.id).where(Game.name == preferred_name))
    if result.scalar_one_or_none() is not None:
        alternate = (igdb_meta.title or "").strip() if igdb_meta else ""
        result = await db.execute(select(Game.id).where(Game.name == alternate)) if alternate else None
        if result is not None and result.scalar_one_or_none() is None:
            preferred_name = alternate
        else:
            preferred_name = f"{preferred_name} [Twitch {category_id or 'category'}]"
            result = await db.execute(select(Game.id).where(Game.name == preferred_name))
            if result.scalar_one_or_none() is not None:
                preferred_name = (
                    f"{preferred_name} #{(igdb_meta.source_game_id if igdb_meta else category_id)}"
                )

    now = _utcnow()
    game = Game(
        name=preferred_name,
        slug=await make_unique_slug(db, preferred_name),
        twitch_category_id=category_id,
        created_at=now,
        updated_at=now,
    )
    db.add(game)
    await db.flush()
    return game


async def _upsert_twitch_category(
    db,
    *,
    category_id: str,
    game: Game,
    category_name: str,
    source: str,
) -> bool:
    now = _utcnow()
    mapping = await db.get(GameTwitchCategory, category_id)
    if mapping is not None and int(mapping.game_id) != int(game.id):
        logger.error(
            "Twitch category %s is already linked to game_id=%s; refusing "
            "to remap it to game_id=%s",
            category_id,
            mapping.game_id,
            game.id,
        )
        return False

    if mapping is None:
        db.add(
            GameTwitchCategory(
                twitch_category_id=category_id,
                game_id=int(game.id),
                category_name=category_name,
                source=source,
                first_seen_at=now,
                last_seen_at=now,
            )
        )
    else:
        mapping.category_name = category_name or mapping.category_name
        mapping.last_seen_at = now
        # Keep a manual/imported provenance when runtime merely observes it.
        if mapping.source == "runtime":
            mapping.source = source

    if not game.twitch_category_id:
        game.twitch_category_id = category_id
    return True


async def sync_runtime_category(
    *,
    category_id: str | None,
    category_name: str | None,
) -> int | None:
    """Resolve a Twitch category to a game and fetch exact IGDB metadata.

    Twitch's IGDB ID is authoritative. Name search is retained only when Twitch
    supplies no IGDB ID. Known non-game categories are persisted as stream
    categories but never queried in IGDB.
    """
    category_id = str(category_id or "").strip() or None
    category_name = (category_name or "").strip()
    if not category_name and not category_id:
        return None

    non_game = is_non_igdb_category(category_name)
    if category_id:
        # A known mapping is authoritative (including manual fixes). Avoid
        # unnecessary Twitch/IGDB calls for categories already enriched.
        async with AsyncSessionLocal() as db:
            mapping = await db.get(GameTwitchCategory, category_id)
            game = (
                await db.get(Game, int(mapping.game_id))
                if mapping is not None
                else None
            )
            if game is None:
                result = await db.execute(
                    select(Game)
                    .where(Game.twitch_category_id == category_id)
                    .limit(1)
                )
                game = result.scalar_one_or_none()
            if game is not None:
                current_meta = await db.get(GameMetadataIGDB, int(game.id))
                has_igdb_mapping = bool(
                    current_meta
                    and current_meta.igdb_id
                    and not current_meta.igdb_id.startswith("pending-")
                )
                if non_game or has_igdb_mapping:
                    await _upsert_twitch_category(
                        db,
                        category_id=category_id,
                        game=game,
                        category_name=category_name,
                        source="runtime",
                    )
                    await db.commit()
                    return int(game.id)

    twitch_game = None
    if category_id and not non_game:
        try:
            twitch_game = await twitch_service.get_game_by_category_id(category_id)
        except Exception:
            logger.exception(
                "Could not resolve Twitch category metadata for id=%s",
                category_id,
            )

    helix_name = str((twitch_game or {}).get("name") or "").strip()
    resolved_name = helix_name or category_name
    non_game = non_game or is_non_igdb_category(resolved_name)
    igdb_id = str((twitch_game or {}).get("igdb_id") or "").strip() or None

    igdb_meta = await _fetch_igdb_metadata(
        igdb_id=igdb_id,
        category_name=resolved_name,
        non_game=non_game,
    )

    if igdb_id and igdb_meta and str(igdb_meta.source_game_id) != igdb_id:
        logger.error(
            "IGDB returned id=%s for Twitch igdb_id=%s; refusing metadata write",
            igdb_meta.source_game_id,
            igdb_id,
        )
        igdb_meta = None

    async with AsyncSessionLocal() as db:
        game: Game | None = None
        existing_mapping = (
            await db.get(GameTwitchCategory, category_id)
            if category_id
            else None
        )
        if existing_mapping is not None:
            game = await db.get(Game, int(existing_mapping.game_id))
        elif category_id:
            result = await db.execute(
                select(Game).where(Game.twitch_category_id == category_id).limit(2)
            )
            legacy_matches = result.scalars().all()
            if len(legacy_matches) == 1:
                game = legacy_matches[0]

        # A category already linked in the DB is authoritative (manual fixes
        # included). Otherwise, use Twitch's exact IGDB ID to locate the game.
        if game is None and igdb_id:
            metadata_result = await db.execute(
                select(GameMetadataIGDB).where(GameMetadataIGDB.igdb_id == igdb_id)
            )
            metadata_row = metadata_result.scalar_one_or_none()
            if metadata_row is not None:
                game = await db.get(Game, int(metadata_row.game_id))

        if game is None and not igdb_id and resolved_name:
            candidates = await _find_name_candidates(db, resolved_name)
            safe_candidates = [
                candidate
                for candidate in candidates
                if non_game
                or not candidate.twitch_category_id
                or str(candidate.twitch_category_id) == category_id
            ]
            if len(safe_candidates) == 1:
                game = safe_candidates[0]

        if game is None:
            game = await _create_category_game(
                db,
                category_id=category_id,
                category_name=resolved_name or category_name,
                igdb_meta=igdb_meta,
            )

        if category_id:
            linked = await _upsert_twitch_category(
                db,
                category_id=category_id,
                game=game,
                category_name=resolved_name or category_name,
                source="runtime",
            )
            if not linked:
                await db.rollback()
                return int(game.id)

        if igdb_meta is not None and not non_game:
            existing_result = await db.execute(
                select(GameMetadataIGDB).where(
                    GameMetadataIGDB.game_id == int(game.id)
                )
            )
            existing_meta = existing_result.scalar_one_or_none()
            wanted_igdb_id = str(igdb_meta.source_game_id)
            if (
                existing_meta is not None
                and existing_meta.igdb_id
                and not existing_meta.igdb_id.startswith("pending-")
                and existing_meta.igdb_id != wanted_igdb_id
            ):
                logger.warning(
                    "Keeping existing IGDB mapping %s for game_id=%s; "
                    "category suggested %s",
                    existing_meta.igdb_id,
                    game.id,
                    wanted_igdb_id,
                )
            else:
                owner_result = await db.execute(
                    select(GameMetadataIGDB.game_id).where(
                        GameMetadataIGDB.igdb_id == wanted_igdb_id,
                        GameMetadataIGDB.game_id != int(game.id),
                    )
                )
                owner_id = owner_result.scalar_one_or_none()
                if owner_id is not None:
                    logger.warning(
                        "IGDB id %s already belongs to game_id=%s; "
                        "not attaching it to game_id=%s",
                        wanted_igdb_id,
                        owner_id,
                        game.id,
                    )
                else:
                    await apply_igdb_patch(
                        db,
                        game_id=int(game.id),
                        igdb_id=wanted_igdb_id,
                        patch=_metadata_patch(igdb_meta),
                    )

        await db.commit()
        return int(game.id)


__all__ = [
    "is_non_igdb_category",
    "normalize_category_name",
    "sync_runtime_category",
]
