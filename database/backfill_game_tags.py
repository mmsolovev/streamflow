"""
Backfill game tags. Supports explicit IGDB id override to avoid search misses.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import exists, select

from database.db import AsyncSessionLocal
from database.models import (
    Game,
    GameMetadataIGDB,
    Genre,
    Platform,
    game_genres,
    game_platforms,
)
from pipeline.ingest.igdb_api import fetch_igdb_metadata, fetch_igdb_metadata_by_id
from pipeline.load.load_game_meta import apply_igdb_patch, link_igdb_genres_and_platforms
from pipeline.transform.igdb_transform import parse_release_date


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _as_payload(value) -> dict | None:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    return value if isinstance(value, dict) else None


def _igdb_score(payload: dict) -> float | None:
    total = payload.get("total_rating")
    if total is None:
        return None
    try:
        return round(float(total), 1)
    except (TypeError, ValueError):
        return None


async def _missing_dictionary_names(session, payload: dict) -> list[str]:
    missing: list[str] = []
    for key, model in (("genres", Genre), ("platforms", Platform)):
        for entry in payload.get(key) or []:
            if not isinstance(entry, dict):
                continue
            name = (entry.get("name") or "").strip()
            if not name:
                continue
            found = (await session.execute(select(model.id).where(model.name == name).limit(1))).first()
            if found is None:
                missing.append(f"{key}:{name}")
    return missing


async def _fetch_and_store(session, game: Game, igdb_id_override: str | None = None) -> tuple[dict | None, str | None]:
    """Fetch IGDB metadata, store it, and return (payload, note).

    If the resolved IGDB id already belongs to another game (duplicate row), the
    id is not overwritten (unique constraint) but the payload is still stored so
    tags can be linked.
    """
    meta = None
    if igdb_id_override:
        meta = await fetch_igdb_metadata_by_id(igdb_id_override)
    if meta is None:
        meta = await fetch_igdb_metadata(game.name)
    if meta is None or not meta.source_payload:
        return None, None

    payload = json.loads(meta.source_payload)
    release_date, _ = parse_release_date(payload.get("first_release_date"))
    patch = {
        "igdb_id": meta.source_game_id,
        "igdb_name": meta.title,
        "description_en": meta.description_short,
        "release_date": release_date,
        "steam_url": meta.steam_url,
        "cover_url": meta.cover_url,
        "igdb_score": _igdb_score(payload),
        "raw_payload": payload,
        "synced_at": _utcnow(),
    }

    note = None
    conflict = (
        await session.execute(
            select(GameMetadataIGDB.game_id)
            .where(GameMetadataIGDB.igdb_id == meta.source_game_id, GameMetadataIGDB.game_id != game.id)
            .limit(1)
        )
    ).first()
    if conflict is not None:
        patch.pop("igdb_id", None)
        note = f"igdb_id {meta.source_game_id} already owned by game {conflict[0]}; kept payload, id unchanged"

    await apply_igdb_patch(session, game_id=game.id, igdb_id=meta.source_game_id, patch=patch)
    return payload, note


def _parse_game_ids(raw: list[str]) -> list[int]:
    out: list[int] = []
    for chunk in raw:
        for part in str(chunk).split(","):
            part = part.strip()
            if part:
                out.append(int(part))
    return out


def _parse_overrides(raw: list[str]) -> dict[int, str]:
    out: dict[int, str] = {}
    for chunk in raw:
        for part in str(chunk).split(","):
            if "=" not in part:
                continue
            gid_str, iid = part.split("=", 1)
            try:
                out[int(gid_str.strip())] = iid.strip()
            except ValueError:
                continue
    return out


async def _select_targets(session, *, explicit_ids: list[int], all_games: bool, fetch_missing: bool):
    if explicit_ids:
        return list(
            (await session.execute(select(Game).where(Game.id.in_(explicit_ids)).order_by(Game.id))).scalars().all()
        )
    if fetch_missing and not all_games:
        return list(
            (
                await session.execute(
                    select(Game)
                    .join(GameMetadataIGDB, GameMetadataIGDB.game_id == Game.id)
                    .where(GameMetadataIGDB.raw_payload.is_(None))
                    .order_by(Game.id)
                )
            )
            .scalars()
            .all()
        )
    base = (
        select(Game)
        .join(GameMetadataIGDB, GameMetadataIGDB.game_id == Game.id)
        .where(GameMetadataIGDB.raw_payload.isnot(None))
    )
    if not all_games:
        base = base.where(
            ~exists(select(1).select_from(game_genres).where(game_genres.c.game_id == Game.id)),
            ~exists(select(1).select_from(game_platforms).where(game_platforms.c.game_id == Game.id)),
        )
    return list((await session.execute(base.order_by(Game.id))).scalars().all())


async def main_async(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Backfill game tags (genres/platforms) from IGDB data.")
    parser.add_argument("--game-id", action="append", default=[], help="Game id(s), repeatable or comma-separated.")
    parser.add_argument("--all", action="store_true", help="Process every game that has a raw_payload.")
    parser.add_argument("--fetch-missing", action="store_true", help="Fetch IGDB metadata when raw_payload is missing.")
    parser.add_argument(
        "--refetch",
        action="store_true",
        help="Force re-fetch (by name or --force-igdb-id) and REPLACE payload + genre/platform links.",
    )
    parser.add_argument("--force-igdb-id", action="append", default=[], help="Override: gid=igdb_id (e.g. 445=314252).")
    args = parser.parse_args(argv)

    explicit_ids = _parse_game_ids(args.game_id)
    overrides = _parse_overrides(args.force_igdb_id)

    async with AsyncSessionLocal() as session:
        targets = await _select_targets(
            session, explicit_ids=explicit_ids, all_games=args.all, fetch_missing=args.fetch_missing
        )
        found = {g.id for g in targets}
        for gid in explicit_ids:
            if gid not in found:
                print(f"WARN: game id {gid} not found")

        print(f"Targets: {len(targets)}")
        linked = fetched = skipped = 0

        for game in targets:
            try:
                async with session.begin_nested():
                    meta_row = (
                        await session.execute(select(GameMetadataIGDB).where(GameMetadataIGDB.game_id == game.id))
                    ).scalar_one_or_none()
                    payload = _as_payload(meta_row.raw_payload) if meta_row is not None else None
                    notes: list[str] = []

                    if args.refetch:
                        payload, fetch_note = await _fetch_and_store(session, game, overrides.get(game.id))
                        if payload is None:
                            print(f"  SKIP id={game.id} {game.name!r}: no IGDB match")
                            skipped += 1
                            continue
                        fetched += 1
                        if fetch_note:
                            notes.append(fetch_note)
                        await session.execute(game_genres.delete().where(game_genres.c.game_id == game.id))
                        await session.execute(game_platforms.delete().where(game_platforms.c.game_id == game.id))
                        notes.append("replaced links")
                    elif payload is None:
                        if not args.fetch_missing:
                            print(f"  SKIP id={game.id} {game.name!r}: no raw_payload (use --fetch-missing)")
                            skipped += 1
                            continue
                        payload, fetch_note = await _fetch_and_store(session, game, overrides.get(game.id))
                        if payload is None:
                            print(f"  SKIP id={game.id} {game.name!r}: no IGDB match")
                            skipped += 1
                            continue
                        fetched += 1
                        if fetch_note:
                            notes.append(fetch_note)

                    missing = await _missing_dictionary_names(session, payload)
                    await link_igdb_genres_and_platforms(session, game_id=game.id, payload=payload)
                    linked += 1
                    if missing:
                        notes.append(f"missing dict rows: {', '.join(missing)}")
                    suffix = f"  [{'; '.join(notes)}]" if notes else ""
                    print(f"  LINK id={game.id} {game.name!r}{suffix}")
            except Exception as exc:  # noqa: BLE001 - keep going across games
                print(f"  ERROR id={game.id} {game.name!r}: {exc.__class__.__name__}: {exc}")
                skipped += 1

        await session.commit()
        print(f"Done: linked={linked}, fetched={fetched}, skipped={skipped}")
    return 0


def main() -> int:
    return asyncio.run(main_async(sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
