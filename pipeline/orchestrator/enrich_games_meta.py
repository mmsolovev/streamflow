from __future__ import annotations

"""
Orchestrator job: enrich `games_meta` table (HLTB hours, Steam URL, platforms, genres).

This job operates directly on the SQLite DB (`storage/streams.db`) and maintains its own cache under
`storage/cache/enrich_games_meta.json`.
"""

import argparse
import asyncio
import json
import shutil
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any


def _project_root() -> Path:
    # .../pipeline/orchestrator/enrich_games_meta.py -> project root
    return Path(__file__).resolve().parents[2]


def _db_path() -> Path:
    return _project_root() / "storage" / "streams.db"


def _cache_path() -> Path:
    return _project_root() / "storage" / "cache" / "enrich_games_meta.json"


def _now_ts() -> int:
    return int(time.time())


def _normalize_key(value: str) -> str:
    return " ".join((value or "").casefold().split())


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def _parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def _normalize_genre_token(token: str) -> str:
    if _normalize_key(token) == "role-playing (rpg)":
        return "RPG"
    return token.strip()


def _normalize_genres_text(genres_text: str | None) -> str | None:
    tokens = [_normalize_genre_token(t) for t in _parse_csv(genres_text)]
    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        key = _normalize_key(t)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(t)
    return ", ".join(out) if out else None


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


def _select_candidates(con: sqlite3.Connection) -> list[dict[str, Any]]:
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    rows = cur.execute(
        """
        SELECT
            gm.game_id,
            g.name AS game_name,
            gm.hltb_hours,
            gm.steam_url,
            gm.platforms_text,
            gm.genres_text
        FROM games_meta gm
        JOIN games g ON g.id = gm.game_id
        WHERE
            (gm.hltb_hours IS NULL OR gm.hltb_hours <= 0)
            OR gm.steam_url IS NULL OR trim(gm.steam_url) = ''
            OR gm.platforms_text IS NULL OR trim(gm.platforms_text) = ''
            OR gm.genres_text IS NULL OR trim(gm.genres_text) = ''
        ORDER BY gm.game_id
        """
    ).fetchall()
    return [dict(r) for r in rows]


def _update_game_meta(
    con: sqlite3.Connection,
    *,
    game_id: int,
    patch: dict[str, Any],
) -> None:
    if not patch:
        return
    cols = sorted(patch.keys())
    assignments = ", ".join(f"{c} = ?" for c in cols)
    params = [patch[c] for c in cols] + [game_id]
    con.execute(f"UPDATE games_meta SET {assignments} WHERE game_id = ?", params)


async def _fetch_igdb_metadata(game_name: str):
    # Lazy import so the script can still run with --skip-igdb even if deps are missing.
    from services.recommendation_metadata_service import fetch_recommendation_metadata

    return await fetch_recommendation_metadata(game_name)


def _hltb_search_best(
    game_name: str,
    *,
    min_similarity: float,
):
    # Lazy import so the script can still run with --skip-hltb even if deps are missing.
    import re

    from howlongtobeatpy import HowLongToBeat

    def sanitize(value: str) -> str:
        sanitized = re.sub(r"[^\w\s:+'\-.]", " ", value, flags=re.UNICODE)
        return " ".join(sanitized.split())

    client = HowLongToBeat()
    queries = [game_name]
    sanitized = sanitize(game_name)
    if sanitized and sanitized != game_name:
        queries.append(sanitized)

    best_match = None
    best_similarity = 0.0

    for q in queries:
        results = client.search(q) or []
        for r in results:
            name = str(getattr(r, "game_name", "") or "")
            sim = float(getattr(r, "similarity", 0.0) or 0.0)
            if sim > best_similarity:
                best_match = r
                best_similarity = sim

    if best_match is None or best_similarity < float(min_similarity):
        return None

    hours = getattr(best_match, "main_story", None)
    if hours is None:
        return None

    return {
        "hltb_hours": float(hours),
        "game_name": str(getattr(best_match, "game_name", "") or ""),
        "similarity": float(best_similarity),
    }


async def async_main() -> int:
    parser = argparse.ArgumentParser(description="Enrich games_meta in streams.db (HLTB + IGDB).")
    parser.add_argument("--db", default=str(_db_path()), help="Path to streams.db")
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

    db_path = Path(args.db)
    if not db_path.exists():
        raise SystemExit(f"DB not found: {db_path}")

    cache_path = _cache_path()
    cache = _ensure_cache_shape(_load_cache(cache_path))

    if args.apply and args.backup:
        backup_path = _backup_db(db_path)
        print(f"Backup: {backup_path}")

    con = sqlite3.connect(db_path)
    try:
        candidates = _select_candidates(con)
        if args.only_game_id:
            candidates = [c for c in candidates if int(c["game_id"]) == int(args.only_game_id)]
        if args.limit and args.limit > 0:
            candidates = candidates[: args.limit]

        if not candidates:
            print("Nothing to do: no candidates selected.")
            return 0

        if args.apply:
            con.execute("BEGIN")

        updated_games = 0
        updated_fields = 0
        hltb_calls = 0
        igdb_calls = 0
        hltb_last_call_at = 0.0

        for idx, row in enumerate(candidates, start=1):
            game_id = int(row["game_id"])
            game_name = str(row.get("game_name") or "")

            want_hltb = not isinstance(row.get("hltb_hours"), (int, float)) or float(row.get("hltb_hours") or 0) <= 0
            want_steam = _is_blank(row.get("steam_url"))
            want_platforms = _is_blank(row.get("platforms_text"))
            want_genres = _is_blank(row.get("genres_text"))
            want_igdb = want_steam or want_platforms or want_genres

            patch: dict[str, Any] = {}
            key = _normalize_key(game_name)

            # ---- HLTB ----
            if want_hltb and not args.skip_hltb and key:
                hltb_entry = cache["hltb"].get(key) if key else None
                ttl_seconds = max(0, int(args.hltb_cache_ttl_days) * 24 * 60 * 60)
                if (
                    isinstance(hltb_entry, dict)
                    and (_now_ts() - int(hltb_entry.get("updated_at") or 0)) < ttl_seconds
                    and isinstance(hltb_entry.get("hltb_hours"), (int, float))
                ):
                    patch["hltb_hours"] = float(hltb_entry["hltb_hours"])
                else:
                    since_last = time.time() - hltb_last_call_at
                    delay = float(args.hltb_delay_seconds)
                    if since_last < delay:
                        await asyncio.sleep(delay - since_last)

                    result = await asyncio.to_thread(
                        _hltb_search_best,
                        game_name,
                        min_similarity=float(args.hltb_min_similarity),
                    )
                    hltb_last_call_at = time.time()
                    hltb_calls += 1

                    if isinstance(result, dict) and isinstance(result.get("hltb_hours"), (int, float)):
                        patch["hltb_hours"] = float(result["hltb_hours"])
                        cache["hltb"][key] = {
                            "hltb_hours": float(result["hltb_hours"]),
                            "matched_name": result.get("game_name"),
                            "similarity": float(result.get("similarity") or 0.0),
                            "updated_at": _now_ts(),
                        }
                    else:
                        cache["hltb"][key] = {"hltb_hours": None, "updated_at": _now_ts()}

            # ---- IGDB ----
            if want_igdb and not args.skip_igdb and key:
                igdb_entry = cache["igdb"].get(key)
                ttl_seconds = max(0, int(args.igdb_cache_ttl_days) * 24 * 60 * 60)
                cached_ok = isinstance(igdb_entry, dict) and (_now_ts() - int(igdb_entry.get("updated_at") or 0)) < ttl_seconds

                if cached_ok:
                    meta = igdb_entry
                else:
                    meta_obj = await _fetch_igdb_metadata(game_name)
                    igdb_calls += 1
                    meta = None
                    if meta_obj is not None:
                        meta = {
                            "steam_url": getattr(meta_obj, "steam_url", None),
                            "platforms_text": getattr(meta_obj, "platforms_text", None),
                            "genres_text": getattr(meta_obj, "genres_text", None),
                        }
                    cache["igdb"][key] = {"updated_at": _now_ts(), **(meta or {})}

                if isinstance(meta, dict):
                    if want_steam and meta.get("steam_url"):
                        patch["steam_url"] = str(meta["steam_url"]).strip() or None
                    if want_platforms and meta.get("platforms_text"):
                        patch["platforms_text"] = str(meta["platforms_text"]).strip() or None
                    if want_genres and meta.get("genres_text"):
                        patch["genres_text"] = _normalize_genres_text(str(meta["genres_text"]))

            if not patch:
                continue

            updated_games += 1
            updated_fields += len(patch)
            preview = ", ".join(f"{k}={patch[k]!r}" for k in sorted(patch.keys()))
            print(f"[{idx}/{len(candidates)}] game_id={game_id} {game_name}: {preview}")

            if args.apply:
                _update_game_meta(con, game_id=game_id, patch=patch)

        if args.apply:
            con.commit()
        else:
            con.rollback()

        _save_cache(cache_path, cache)

        mode = "APPLIED" if args.apply else "DRY-RUN"
        print(
            f"{mode}: updated_games={updated_games}, updated_fields={updated_fields}, "
            f"hltb_calls={hltb_calls}, igdb_calls={igdb_calls}"
        )
        return 0
    except Exception:
        if args.apply:
            con.rollback()
        raise
    finally:
        con.close()


def main() -> None:
    # Ensure imports like `services.*` work when running as a script.
    sys.path.insert(0, str(_project_root()))
    raise SystemExit(asyncio.run(async_main()))


if __name__ == "__main__":
    main()

