from __future__ import annotations

"""
Orchestrator: TwitchTracker stream detail pages → database.

Pipeline:
1. Parse HTML stream pages from storage/pages/
2. Fetch VODs from Twitch API for stream_id matching
3. For each stream page:
   a. Upsert stream (find by Twitch id / start time, update metrics, write external_id)
   b. Upsert title changes into stream_titles
   c. Upsert stream_games with per-game metrics
4. Recompute game_stats for affected games (idempotent, no additive increment)
5. Enrich new games with IGDB + HLTB (immediate)
"""

import asyncio
import json
import time
from pathlib import Path

import aiohttp

import config.settings as settings
from database.db import AsyncSessionLocal
from database.models import Game, Stream, StreamRecording
from pipeline.ingest.twitch_api import TwitchTokenExpiredError, fetch_user_id, fetch_vods
from pipeline.ingest.twitchtracker_parser import parse_stream_page_html
from pipeline.transform.streams_transform import (
    build_vods_index,
    pick_vod_candidates,
)
from pipeline.transform.stream_page_transform import resolve_external_id
from pipeline.load.load_stream_page import (
    upsert_stream_from_page,
    upsert_stream_games_from_page,
    upsert_stream_titles,
)
from pipeline.load.load_game_meta import (
    apply_igdb_patch,
    apply_hltb_patch,
    link_igdb_genres_and_platforms,
    select_igdb_enrichment_candidates,
)
from pipeline.ingest.hltb_client import search_best
from pipeline.ingest.igdb_api import fetch_igdb_metadata
from services.stats_aggregation_service import recompute_game_stats
from sqlalchemy import select


def _log(message: str) -> None:
    print(message, flush=True)


def _default_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _pages_dir(root: Path) -> Path:
    return root / "storage" / "pages"


def _find_stream_pages(pages_dir: Path) -> list[Path]:
    """Find all stream_*.html files in pages directory."""
    return sorted(pages_dir.glob("stream_*.html"))


def _normalize_key(value: str) -> str:
    return " ".join((value or "").casefold().split())


async def _fetch_vods_data(
    session: aiohttp.ClientSession,
    *,
    client_id: str,
    access_token: str,
    channel_login: str,
) -> tuple[dict, list[dict]]:
    """Fetch all VODs, return (vods_by_date_index, raw_vods_list)."""
    from services.token_service import try_refresh_token

    try:
        user_id = await fetch_user_id(
            session,
            client_id=client_id,
            access_token=access_token,
            channel_login=channel_login,
        )
    except TwitchTokenExpiredError:
        _log("Token expired, attempting refresh...")
        new_token = await try_refresh_token()
        settings.TWITCH_ACCESS_TOKEN = new_token
        user_id = await fetch_user_id(
            session,
            client_id=client_id,
            access_token=new_token,
            channel_login=channel_login,
        )

    vods = await fetch_vods(
        session,
        client_id=client_id,
        access_token=access_token,
        user_id=user_id,
    )
    return build_vods_index(vods), vods


async def _sync_vod_recordings(
    session,
    streams: list[Stream],
    vods_by_date: dict,
    vod_urls_all: set[str],
    vods: list[dict] | None = None,
) -> int:
    """Привязать VOD к стримам и записать в `stream_recordings`.

    Сначала точное совпадение `vod.stream_id` == `streams.external_id`,
    затем fallback по времени для стримов, у которых записи ещё нет.
    Возвращает число добавленных/обновлённых записей.
    """
    from datetime import timedelta

    from services import recording_service

    vods_by_broadcast: dict[str, dict] = {}
    for vod in vods or []:
        broadcast = str(vod.get("stream_id") or "").strip()
        if broadcast:
            vods_by_broadcast[broadcast] = vod

    streams_by_external = {
        str(stream.external_id): stream
        for stream in streams
        if stream.external_id
    }

    matched_streams: set[int] = set()
    used_vod_ids: set[str] = set()
    added = 0

    # --- 1. Точное совпадение по broadcast id -----------------------------
    for broadcast, vod in vods_by_broadcast.items():
        stream = streams_by_external.get(broadcast)
        if stream is None:
            continue
        recording = await recording_service.upsert_from_vod(
            session, stream_id=int(stream.id), vod=vod
        )
        if recording is None:
            continue
        matched_streams.add(int(stream.id))
        vod_id = str(vod.get("id") or "").strip()
        if vod_id:
            used_vod_ids.add(vod_id)
        added += 1
        _log(f"  = VOD for stream id={stream.id}: {recording.url[:70]}")

    # --- 2. Fallback по времени для стримов без записи --------------------
    # Записи, уже привязанные ранее, не трогаем: повторный импорт не должен
    # добавлять второй VOD к тому же стриму. У стрима с реконнектами записи
    # приходят точным совпадением по broadcast id.
    if streams:
        existing_result = await session.execute(
            select(StreamRecording.stream_id).where(
                StreamRecording.source == "twitch",
                StreamRecording.stream_id.in_([int(item.id) for item in streams]),
            )
        )
        matched_streams.update(
            int(row[0]) for row in existing_result.all() if row[0] is not None
        )

    for stream in streams:
        if int(stream.id) in matched_streams:
            continue
        if not stream.started_at:
            _log(f"  Stream id={stream.id}: no started_at, skipping VOD match")
            continue

        if stream.ended_at:
            stream_end = stream.ended_at
        elif stream.duration_minutes:
            stream_end = stream.started_at + timedelta(minutes=stream.duration_minutes)
        else:
            stream_end = stream.started_at + timedelta(hours=12)

        # Широкое окно — страховка для legacy-строк, где время могло быть
        # записано в локальной зоне.
        vod_window_start = stream.started_at - timedelta(hours=6)
        vod_window_end = stream_end + timedelta(hours=6)

        candidates = pick_vod_candidates(
            vods_by_date=vods_by_date,
            stream_date=stream.started_at.date(),
        )
        for vod in candidates:
            vod_id = str(vod.get("id") or "").strip()
            if vod_id and vod_id in used_vod_ids:
                continue
            fields = recording_service.fields_from_vod(vod)
            recorded_at = fields["recorded_at"]
            if recorded_at is None or not (
                vod_window_start <= recorded_at <= vod_window_end
            ):
                continue

            recording = await recording_service.upsert_from_vod(
                session, stream_id=int(stream.id), vod=vod
            )
            if recording is None:
                continue
            matched_streams.add(int(stream.id))
            if vod_id:
                used_vod_ids.add(vod_id)
            added += 1
            _log(
                f"  + Legacy VOD for stream id={stream.id}: "
                f"{recording.url[:70]} ({fields['duration_minutes']}min)"
            )
            break

    # --- 3. Истёкшие записи: скрыть, но не удалять ------------------------
    if vod_urls_all:
        hidden = await recording_service.mark_missing_unavailable(
            session,
            keep_urls=vod_urls_all,
            keep_video_ids=used_vod_ids,
        )
        if hidden:
            _log(f"  Marked {hidden} unavailable VOD recording(s)")

    return added


async def _enrich_new_games(
    db_session,
    game_cache: dict[str, Game],
    only_game_ids: set[int] | None = None,
) -> tuple[int, int, int, int]:
    """Enrich games with HLTB + IGDB. If only_game_ids is provided, only those games."""
    HLTB_DELAY_SECONDS = 1.0
    HLTB_REQUEST_TIMEOUT_SECONDS = 10.0
    HLTB_MIN_SIMILARITY = 0.6

    # Non-gaming categories that should not be enriched via IGDB/HLTB
    SKIP_GAMES: set[str] = {
        "irl", "just chatting", "asmr", "mukbang", "hot tub", "beach",
        "pools", "talk shows", "science & technology", "food & drink",
        "fitness", "travel", "outdoors", "art", "music", "dance",
    }

    candidates = await select_igdb_enrichment_candidates(db_session)
    if only_game_ids is not None:
        ids = {int(i) for i in only_game_ids if int(i) > 0}
        candidates = [row for row in candidates if int(row.game_id) in ids]
    if not candidates:
        return (0, 0, 0, 0)

    hltb_last_call_at = 0.0
    updated_games = 0
    updated_fields = 0
    hltb_calls = 0
    igdb_calls = 0

    for idx, row in enumerate(candidates, start=1):
        if idx == 1 or idx % 10 == 0 or idx == len(candidates):
            _log(f"Games meta enrichment progress: {idx}/{len(candidates)}")
        key = _normalize_key(row.game_name)
        if not key or key in SKIP_GAMES:
            continue

        hltb_patch = {}
        if not row.has_hltb:
            since_last = time.time() - hltb_last_call_at
            if since_last < HLTB_DELAY_SECONDS:
                await asyncio.sleep(HLTB_DELAY_SECONDS - since_last)
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(search_best, row.game_name, min_similarity=HLTB_MIN_SIMILARITY),
                    timeout=HLTB_REQUEST_TIMEOUT_SECONDS,
                )
            except asyncio.TimeoutError:
                result = None
            hltb_last_call_at = time.time()
            hltb_calls += 1
            if result is not None:
                hltb_patch["hltb_all_styles"] = float(result.hltb_hours)

        igdb_patch = {}
        if not row.has_igdb:
            meta = await fetch_igdb_metadata(row.game_name)
            igdb_calls += 1
            if meta is not None:
                igdb_patch = {k: v for k, v in {
                    "steam_url": getattr(meta, "steam_url", None),
                    "description_en": getattr(meta, "description_short", None),
                    "raw_payload": getattr(meta, "source_payload", None),
                }.items() if v}

        if hltb_patch:
            if await apply_hltb_patch(db_session, game_id=row.game_id, patch=hltb_patch):
                updated_games += 1
                updated_fields += len(hltb_patch)
        if igdb_patch:
            if await apply_igdb_patch(db_session, game_id=row.game_id, patch=igdb_patch):
                updated_games += 1
                updated_fields += len(igdb_patch)
            # Link genres/platforms from the stored raw_payload (e.g. game_genres).
            raw = getattr(meta, "source_payload", None)
            if raw:
                try:
                    payload = json.loads(raw)
                except (ValueError, TypeError):
                    payload = None
                if payload:
                    await link_igdb_genres_and_platforms(
                        db_session,
                        game_id=row.game_id,
                        payload=payload,
                    )

    return (updated_games, updated_fields, hltb_calls, igdb_calls)


async def run() -> int:
    from services.token_service import ensure_valid_token

    if not settings.TWITCHTRACKER_IMPORT_ENABLED:
        _log("TwitchTracker import disabled by TWITCHTRACKER_IMPORT_ENABLED")
        return 0

    try:
        new_token = await ensure_valid_token()
        settings.TWITCH_ACCESS_TOKEN = new_token
    except RuntimeError as exc:
        _log(f"Token validation failed: {exc}")
        return 1

    root = _default_project_root()
    pages_dir = _pages_dir(root)
    page_files = _find_stream_pages(pages_dir)

    if not page_files:
        _log("No stream_*.html files found in storage/pages/")
        return 0

    _log(f"Found {len(page_files)} stream page(s)")

    # Parse all pages
    parsed_pages = []
    rejected_pages = []
    for path in page_files:
        try:
            page = parse_stream_page_html(path)
        except ValueError as exc:
            _log(f"ERROR: skipping {path.name}: {exc}")
            rejected_pages.append(path.name)
            continue
        if page is not None:
            parsed_pages.append(page)
        else:
            _log(f"Skipping {path.name}: failed to parse")

    _log(f"Successfully parsed {len(parsed_pages)} page(s)")
    if rejected_pages:
        _log(
            f"Rejected {len(rejected_pages)} page file(s): {', '.join(rejected_pages)} "
            "— fix them and re-run"
        )

    if not parsed_pages:
        return 1 if rejected_pages else 0

    # Fetch VODs from Twitch API
    vods_by_date: dict = {}
    raw_vods: list[dict] = []
    vod_urls_all: set[str] = set()
    if settings.CLIENT_ID and settings.TWITCH_ACCESS_TOKEN and settings.TWITCH_PRIMARY_CHANNEL:
        _log("Fetching VODs from Twitch API...")
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as http:
            try:
                vods_by_date, raw_vods = await _fetch_vods_data(
                    http,
                    client_id=settings.CLIENT_ID,
                    access_token=settings.TWITCH_ACCESS_TOKEN,
                    channel_login=settings.TWITCH_PRIMARY_CHANNEL,
                )
                vod_urls_all = {str(v.get("url") or "").strip() for v in raw_vods}
                vod_urls_all.discard("")
                _log(f"Fetched VODs for {len(vods_by_date)} date(s), {len(vod_urls_all)} URLs")
            except TwitchTokenExpiredError:
                _log("Failed to fetch VODs: token expired")
            except Exception as exc:
                _log(f"Failed to fetch VODs: {exc}")
    else:
        _log("Skipping VOD fetch: missing Twitch credentials")

    async with AsyncSessionLocal() as session:
        # Pre-load game cache
        from sqlalchemy import select as sa_select
        game_result = await session.execute(sa_select(Game))
        all_games = game_result.scalars().all()
        game_cache = {game.name: game for game in all_games}

        streams_added = 0
        streams_updated = 0
        titles_added = 0
        stream_games_updated = 0
        processed_game_ids: set[int] = set()
        processed_streams: list[Stream] = []

        for page in parsed_pages:
            _log(f"\nProcessing stream: {page.date.date()}")
            twitch_stream_id = resolve_external_id(page, vods_by_date)
            _log(f"  Resolved external_id: {twitch_stream_id or '(date fallback)'}")

            stream, created = await upsert_stream_from_page(session, page, twitch_stream_id)
            if created:
                streams_added += 1
            else:
                streams_updated += 1
            processed_streams.append(stream)

            titles_added += await upsert_stream_titles(session, stream, page)

            stream_games_updated += await upsert_stream_games_from_page(session, stream, page, game_cache)

            for entry in page.games:
                game = game_cache.get(entry.name)
                if game:
                    processed_game_ids.add(int(game.id))

        _log("\nSyncing VOD recordings...")
        vod_recordings_added = await _sync_vod_recordings(
            session, processed_streams, vods_by_date, vod_urls_all, raw_vods,
        )

        _log("\nRecomputing game_stats from stream_games...")
        stats_batch = await recompute_game_stats(
            session,
            processed_game_ids,
            source="twitchtracker",
            reason="parse_twitchtracker",
        )
        stats_changes = getattr(stats_batch, "changes_count", 0)

        _log("Enriching games (IGDB + HLTB)...")
        games_enriched, fields_updated, hltb_calls, igdb_calls = await _enrich_new_games(
            session, game_cache, only_game_ids=processed_game_ids,
        )

        _log("\nCommitting transaction...")
        await session.commit()

        _log("\nStream page import:")
        _log(f"  Streams -> added: {streams_added}, updated: {streams_updated}")
        _log(f"  Titles -> added: {titles_added}")
        _log(f"  Stream games -> updated fields: {stream_games_updated}")
        _log(f"  VOD recordings -> added: {vod_recordings_added}")
        _log(f"  game_stats -> changed fields: {stats_changes}")
        _log(f"  Games enriched: {games_enriched} ({hltb_calls} HLTB, {igdb_calls} IGDB calls)")
        _log("Done!")
        return 1 if rejected_pages else 0


def main() -> None:
    raise SystemExit(asyncio.run(run()))


if __name__ == "__main__":
    main()
