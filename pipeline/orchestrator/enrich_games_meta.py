from __future__ import annotations

"""
Orchestrator job: enrich `games_meta` table (HLTB hours, Steam URL, platforms, genres).

Layering:
- ingest: external lookups (IGDB, HLTB) + local JSON cache
- transform: normalization + decision which fields to fill
- load: read/update GameMeta rows in DB
"""

import argparse
import asyncio
import json
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from database.db import SessionLocal, db_path as _default_db_path_str
from pipeline.ingest.hltb_client import HltbResult, search_best
from pipeline.ingest.igdb_api import fetch_igdb_metadata
from pipeline.load.load_game_meta import apply_games_meta_patch, select_enrichment_candidates
from pipeline.transform.games_transform import IgdbMetaView, build_patch
from pipeline.transform.utils_transform import normalize_key


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _cache_path() -> Path:
    return _project_root() / "storage" / "cache" / "enrich_games_meta.json"


def _now_ts() -> int:
    return int(time.time())


def _load_cache(path: Path) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.stat().st_size == 0:
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_cache(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _ensure_cache_shape(cache: dict[str, Any]) -> dict[str, Any]:
    cache.setdefault("hltb", {})
    cache.setdefault("igdb", {})
    return cache


def _backup_db(db_path: Path) -> Path:
    ts = time.strftime("%Y%m%d-%H%M%S")
    backup_path = db_path.with_name(f"{db_path.name}.bak-{ts}")
    shutil.copyfile(db_path, backup_path)
    return backup_path


@dataclass(frozen=True, slots=True)
class _CachedHltb:
    hltb_hours: float | None
    updated_at: int


def _get_cached_hltb(cache: dict[str, Any], key: str, *, ttl_seconds: int) -> float | None:
    entry = cache.get("hltb", {}).get(key)
    if not isinstance(entry, dict):
        return None
    updated_at = int(entry.get("updated_at") or 0)
    if ttl_seconds > 0 and (_now_ts() - updated_at) >= ttl_seconds:
        return None
    value = entry.get("hltb_hours")
    if isinstance(value, (int, float)) and float(value) > 0:
        return float(value)
    return None


def _put_cached_hltb(cache: dict[str, Any], key: str, value: float | None) -> None:
    cache.setdefault("hltb", {})
    cache["hltb"][key] = {"hltb_hours": value, "updated_at": _now_ts()}


def _get_cached_igdb(cache: dict[str, Any], key: str, *, ttl_seconds: int) -> IgdbMetaView | None:
    entry = cache.get("igdb", {}).get(key)
    if not isinstance(entry, dict):
        return None
    updated_at = int(entry.get("updated_at") or 0)
    if ttl_seconds > 0 and (_now_ts() - updated_at) >= ttl_seconds:
        return None

    return IgdbMetaView(
        steam_url=entry.get("steam_url"),
        platforms_text=entry.get("platforms_text"),
        genres_text=entry.get("genres_text"),
    )


def _put_cached_igdb(cache: dict[str, Any], key: str, meta: IgdbMetaView | None) -> None:
    cache.setdefault("igdb", {})
    payload: dict[str, Any] = {"updated_at": _now_ts()}
    if meta is not None:
        payload.update(
            {
                "steam_url": meta.steam_url,
                "platforms_text": meta.platforms_text,
                "genres_text": meta.genres_text,
            }
        )
    cache["igdb"][key] = payload


async def async_run(
    *,
    apply: bool,
    backup: bool,
    limit: int,
    only_game_id: int,
    skip_hltb: bool,
    skip_igdb: bool,
    hltb_delay_seconds: float,
    hltb_min_similarity: float,
    hltb_cache_ttl_days: int,
    igdb_cache_ttl_days: int,
    cache_path: Path | None = None,
    db_path: Path | None = None,
) -> int:
    db_path = Path(db_path) if db_path is not None else Path(_default_db_path_str)
    if not db_path.exists():
        raise SystemExit(f"DB not found: {db_path}")

    if apply and backup:
        backup_path = _backup_db(db_path)
        print(f"Backup: {backup_path}")

    cache_path = Path(cache_path) if cache_path is not None else _cache_path()
    cache = _ensure_cache_shape(_load_cache(cache_path))

    hltb_ttl_seconds = max(0, int(hltb_cache_ttl_days) * 24 * 60 * 60)
    igdb_ttl_seconds = max(0, int(igdb_cache_ttl_days) * 24 * 60 * 60)

    session = SessionLocal()
    try:
        candidates = select_enrichment_candidates(
            session,
            only_game_id=int(only_game_id),
            limit=int(limit),
        )
        if not candidates:
            print("Nothing to do: no candidates selected.")
            return 0

        updated_games = 0
        updated_fields = 0
        hltb_calls = 0
        igdb_calls = 0
        hltb_last_call_at = 0.0

        for idx, row in enumerate(candidates, start=1):
            key = normalize_key(row.game_name)
            if not key:
                continue

            hltb_hours: float | None = None
            if not skip_hltb:
                hltb_hours = _get_cached_hltb(cache, key, ttl_seconds=hltb_ttl_seconds)
                if hltb_hours is None:
                    since_last = time.time() - hltb_last_call_at
                    delay = float(hltb_delay_seconds)
                    if since_last < delay:
                        await asyncio.sleep(delay - since_last)

                    result = await asyncio.to_thread(
                        search_best,
                        row.game_name,
                        min_similarity=float(hltb_min_similarity),
                    )
                    hltb_last_call_at = time.time()
                    hltb_calls += 1

                    if isinstance(result, HltbResult) and float(result.hltb_hours) > 0:
                        hltb_hours = float(result.hltb_hours)
                        _put_cached_hltb(cache, key, hltb_hours)
                    else:
                        _put_cached_hltb(cache, key, None)

            igdb_view: IgdbMetaView | None = None
            if not skip_igdb:
                igdb_view = _get_cached_igdb(cache, key, ttl_seconds=igdb_ttl_seconds)
                if igdb_view is None:
                    meta_obj = await fetch_igdb_metadata(row.game_name)
                    igdb_calls += 1
                    if meta_obj is not None:
                        igdb_view = IgdbMetaView(
                            steam_url=getattr(meta_obj, "steam_url", None),
                            platforms_text=getattr(meta_obj, "platforms_text", None),
                            genres_text=getattr(meta_obj, "genres_text", None),
                        )
                    _put_cached_igdb(cache, key, igdb_view)

            patch = build_patch(row, hltb_hours=hltb_hours, igdb=igdb_view)
            if not patch:
                continue

            updated_games += 1
            updated_fields += len(patch)
            preview = ", ".join(f"{k}={patch[k]!r}" for k in sorted(patch.keys()))
            print(f"[{idx}/{len(candidates)}] game_id={row.game_id} {row.game_name}: {preview}")

            if apply:
                apply_games_meta_patch(session, game_id=int(row.game_id), patch=patch)

        if apply:
            session.commit()
        else:
            session.rollback()

        _save_cache(cache_path, cache)

        mode = "APPLIED" if apply else "DRY-RUN"
        print(
            f"{mode}: updated_games={updated_games}, updated_fields={updated_fields}, "
            f"hltb_calls={hltb_calls}, igdb_calls={igdb_calls}"
        )
        return 0
    except Exception:
        if apply:
            session.rollback()
        raise
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Enrich games_meta in streams.db (HLTB + IGDB).")
    parser.add_argument("--db", default=str(_default_db_path_str), help="Path to streams.db")
    parser.add_argument("--apply", action="store_true", help="Write changes to DB (default: dry-run).")
    parser.add_argument("--backup", action="store_true", help="Create .bak-* copy of DB before applying.")
    parser.add_argument("--limit", type=int, default=0, help="Max games to process (0 = no limit).")
    parser.add_argument("--only-game-id", type=int, default=0, help="Process only this game_id.")
    parser.add_argument("--skip-hltb", action="store_true", help="Skip HLTB lookup.")
    parser.add_argument("--skip-igdb", action="store_true", help="Skip IGDB lookup.")
    parser.add_argument("--hltb-delay-seconds", type=float, default=2.0, help="Delay between HLTB calls.")
    parser.add_argument("--hltb-min-similarity", type=float, default=0.75, help="Minimum HLTB similarity.")
    parser.add_argument("--hltb-cache-ttl-days", type=int, default=30, help="HLTB cache TTL in days.")
    parser.add_argument("--igdb-cache-ttl-days", type=int, default=30, help="IGDB cache TTL in days.")
    args = parser.parse_args()

    raise SystemExit(
        asyncio.run(
            async_run(
                apply=bool(args.apply),
                backup=bool(args.backup),
                limit=int(args.limit),
                only_game_id=int(args.only_game_id),
                skip_hltb=bool(args.skip_hltb),
                skip_igdb=bool(args.skip_igdb),
                hltb_delay_seconds=float(args.hltb_delay_seconds),
                hltb_min_similarity=float(args.hltb_min_similarity),
                hltb_cache_ttl_days=int(args.hltb_cache_ttl_days),
                igdb_cache_ttl_days=int(args.igdb_cache_ttl_days),
                cache_path=_cache_path(),
                db_path=Path(args.db),
            )
        )
    )


if __name__ == "__main__":
    main()

