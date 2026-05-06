from __future__ import annotations

"""
Orchestrator: storage/*.json -> database + enrichment.

Pipeline order:
- ingest: read twitchtracker JSON files
- load: sync streams and game stats
- load: recompute streams_count
- ingest/load: sync stream VOD URLs from Twitch API
- ingest/transform/load: enrich games_meta from HLTB + IGDB
- transform/load: fill streams.genres_text
"""

import asyncio
import json
from pathlib import Path
import time
from typing import Any

import aiohttp

from config.settings import CLIENT_ID, TWITCH_ACCESS_TOKEN, TWITCH_PRIMARY_CHANNEL
from database.db import SessionLocal
from database.models import Game
from pipeline.ingest.hltb_client import search_best
from pipeline.ingest.igdb_api import fetch_igdb_metadata
from pipeline.ingest.twitch_api import fetch_user_id, fetch_vods
from pipeline.ingest.twitchtracker_parser import load_games_json, load_streams_json
from pipeline.load.load_game_stats import sync_game_stats, update_streams_count
from pipeline.load.load_game_meta import apply_games_meta_patch, select_enrichment_candidates
from pipeline.load.load_streams import sync_streams
from pipeline.load.load_streams import get_stream_context, iter_streams_for_genres, set_stream_genres_text, sync_stream_vod_urls
from pipeline.transform.games_transform import IgdbMetaView, build_patch
from pipeline.transform.streams_transform import compute_stream_genres


def _default_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _cache_path(project_root: Path) -> Path:
    return project_root / "storage" / "cache" / "import_json_to_db_enrich_cache.json"


def _now_ts() -> int:
    return int(time.time())


def _normalize_key(value: str) -> str:
    return " ".join((value or "").casefold().split())


def _load_cache(path: Path) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.stat().st_size == 0:
        return {"hltb": {}, "igdb": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("hltb", {})
    data.setdefault("igdb", {})
    return data


def _save_cache(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _cache_fresh(entry: Any, *, ttl_days: int) -> bool:
    if not isinstance(entry, dict):
        return False
    updated_at = int(entry.get("updated_at") or 0)
    ttl_seconds = max(0, int(ttl_days) * 24 * 60 * 60)
    return (_now_ts() - updated_at) < ttl_seconds


async def _sync_vods(session) -> tuple[int, int]:
    if not (CLIENT_ID and TWITCH_ACCESS_TOKEN and TWITCH_PRIMARY_CHANNEL):
        print("Skipping VOD sync: missing CLIENT_ID/TWITCH_ACCESS_TOKEN/TWITCH_PRIMARY_CHANNEL.")
        return (0, 0)

    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as http:
        user_id = await fetch_user_id(
            http,
            client_id=CLIENT_ID,
            access_token=TWITCH_ACCESS_TOKEN,
            channel_login=TWITCH_PRIMARY_CHANNEL,
        )
        vods = await fetch_vods(
            http,
            client_id=CLIENT_ID,
            access_token=TWITCH_ACCESS_TOKEN,
            user_id=user_id,
        )

    vod_stats = sync_stream_vod_urls(session, vods)
    return (vod_stats.removed_outdated, vod_stats.matched_new)


async def _enrich_games_meta(session, *, cache: dict[str, Any]) -> tuple[int, int, int, int]:
    HLTB_MIN_SIMILARITY = 0.60
    HLTB_DELAY_SECONDS = 1.25
    HLTB_CACHE_TTL_DAYS = 30
    IGDB_CACHE_TTL_DAYS = 30

    candidates = select_enrichment_candidates(session)
    if not candidates:
        return (0, 0, 0, 0)

    updated_games = 0
    updated_fields = 0
    hltb_calls = 0
    igdb_calls = 0
    hltb_last_call_at = 0.0

    for row in candidates:
        patch: dict[str, Any] = {}
        key = _normalize_key(row.game_name)
        if not key:
            continue

        # HLTB
        hltb_hours: float | None = None
        if (row.hltb_hours is None or float(row.hltb_hours or 0) <= 0) and key:
            hltb_entry = cache["hltb"].get(key)
            if _cache_fresh(hltb_entry, ttl_days=HLTB_CACHE_TTL_DAYS) and isinstance(
                hltb_entry.get("hltb_hours"), (int, float)
            ):
                hltb_hours = float(hltb_entry["hltb_hours"])
            else:
                since_last = time.time() - hltb_last_call_at
                if since_last < HLTB_DELAY_SECONDS:
                    await asyncio.sleep(HLTB_DELAY_SECONDS - since_last)
                result = await asyncio.to_thread(
                    search_best,
                    row.game_name,
                    min_similarity=HLTB_MIN_SIMILARITY,
                )
                hltb_last_call_at = time.time()
                hltb_calls += 1

                if result is not None:
                    hltb_hours = float(result.hltb_hours)
                    cache["hltb"][key] = {
                        "hltb_hours": float(result.hltb_hours),
                        "matched_name": result.matched_name,
                        "similarity": float(result.similarity),
                        "updated_at": _now_ts(),
                    }
                else:
                    cache["hltb"][key] = {"hltb_hours": None, "updated_at": _now_ts()}

        # IGDB
        igdb_view: IgdbMetaView | None = None
        need_igdb = not bool((row.steam_url or "").strip()) or not bool((row.platforms_text or "").strip()) or not bool(
            (row.genres_text or "").strip()
        )
        if need_igdb and key:
            igdb_entry = cache["igdb"].get(key)
            if _cache_fresh(igdb_entry, ttl_days=IGDB_CACHE_TTL_DAYS):
                igdb_view = IgdbMetaView(
                    steam_url=igdb_entry.get("steam_url"),
                    platforms_text=igdb_entry.get("platforms_text"),
                    genres_text=igdb_entry.get("genres_text"),
                )
            else:
                meta = await fetch_igdb_metadata(row.game_name)
                igdb_calls += 1
                if meta is not None:
                    igdb_view = IgdbMetaView(
                        steam_url=getattr(meta, "steam_url", None),
                        platforms_text=getattr(meta, "platforms_text", None),
                        genres_text=getattr(meta, "genres_text", None),
                    )
                    cache["igdb"][key] = {
                        "steam_url": igdb_view.steam_url,
                        "platforms_text": igdb_view.platforms_text,
                        "genres_text": igdb_view.genres_text,
                        "updated_at": _now_ts(),
                    }
                else:
                    cache["igdb"][key] = {"updated_at": _now_ts()}

        patch = build_patch(row, hltb_hours=hltb_hours, igdb=igdb_view)
        if not patch:
            continue
        if apply_games_meta_patch(session, game_id=row.game_id, patch=patch):
            updated_games += 1
            updated_fields += len(patch)

    return (updated_games, updated_fields, hltb_calls, igdb_calls)


def _enrich_streams_genres(session) -> int:
    updated = 0
    for stream in iter_streams_for_genres(session, force=False):
        has_participants, game_names, game_genres_texts = get_stream_context(stream)
        new_value = compute_stream_genres(
            title=stream.title,
            has_participants=has_participants,
            game_names=game_names,
            game_genres_texts=game_genres_texts,
        )
        if set_stream_genres_text(session, stream, new_value):
            updated += 1
    return updated


async def run() -> int:
    root = _default_project_root()
    streams_json = root / "storage" / "streams.json"
    games_json = root / "storage" / "games.json"
    cache_path = _cache_path(root)
    cache = _load_cache(cache_path)

    streams_data = load_streams_json(streams_json)
    games_data = load_games_json(games_json)

    session = SessionLocal()
    try:
        game_cache = {game.name: game for game in session.query(Game).all()}

        stream_stats = sync_streams(
            session,
            streams_data,
            game_cache,
            prune_missing=True,
            sync_participants_from_title=True,
        )
        game_stats = sync_game_stats(session, games_data, game_cache, prune_missing=True)
        streams_count_updated = update_streams_count(session)

        vod_removed, vod_matched = await _sync_vods(session)
        games_updated, games_fields_updated, hltb_calls, igdb_calls = await _enrich_games_meta(session, cache=cache)
        streams_genres_updated = _enrich_streams_genres(session)

        session.commit()
        _save_cache(cache_path, cache)

        print("JSON import to DB:")
        print(
            f"Streams -> added: {stream_stats.added}, "
            f"updated: {stream_stats.updated}, "
            f"unchanged: {stream_stats.unchanged}, "
            f"deleted: {stream_stats.deleted}"
        )
        print(
            f"Game stats -> added: {game_stats.added}, "
            f"updated: {game_stats.updated}, "
            f"unchanged: {game_stats.unchanged}, "
            f"deleted: {game_stats.deleted}"
        )
        print(f"GameStats.streams_count updated rows: {streams_count_updated}")
        print("Post-import enrichment:")
        print(f"VOD sync -> removed outdated: {vod_removed}, matched new: {vod_matched}")
        print(
            f"Games meta -> updated games: {games_updated}, updated fields: {games_fields_updated}, "
            f"hltb calls: {hltb_calls}, igdb calls: {igdb_calls}"
        )
        print(f"Streams genres -> updated streams: {streams_genres_updated}")
        print("Done!")
        return 0
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def main() -> None:
    raise SystemExit(asyncio.run(run()))


if __name__ == "__main__":
    main()
