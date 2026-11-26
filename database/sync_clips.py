"""
One-time script: fetch ALL clips from the Tabula Twitch channel
and populate the clips table.

Iterates over streams in the DB and queries Twitch /clips with
started_at / ended_at date filters so no clip is missed.

Creates clip creators as users if missing, links clips to streams,
and resolves game IDs via Twitch API.

Automatically refreshes the access token on 401 errors.

Usage:
    python database/sync_clips.py

Requirements:
    - PostgreSQL running with streams, games, users tables populated
    - CLIENT_ID, TWITCH_ACCESS_TOKEN, TWITCH_REFRESH_TOKEN configured in .env
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

import aiohttp
from sqlalchemy import select, update

from database.db import AsyncSessionLocal
from database.models import Clip, Game, Stream, User
from pipeline.load.load_games import get_or_create_game
from services.user_service import get_or_create_user_by_twitch_id

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

TWITCH_API = "https://api.twitch.tv/helix"
BROADCASTER_LOGIN = "tabula"
CLIPS_PAGE_SIZE = 100
GAMES_PAGE_SIZE = 100
RATE_DELAY = 0.7
_broadcaster_id_cache: dict[str, str] = {}


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _parse_dt(raw: str) -> datetime:
    raw = raw.replace("Z", "+00:00")
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _to_iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_headers(client_id: str, access_token: str) -> dict:
    return {
        "Client-ID": client_id,
        "Authorization": f"Bearer {access_token}",
    }


async def _refresh_token() -> str | None:
    from services.token_service import try_refresh_token
    return await try_refresh_token()


async def _api_get(http, url, headers, params, *, client_id: str):
    """Strict GET with bounded retries; failed pages must never look empty."""
    return await _api_get_retry(
        http, url, headers, params, client_id=client_id, retries=0, refreshed=False
    )


class TwitchClipAPIError(RuntimeError):
    pass


async def _api_get_retry(
    http,
    url,
    headers,
    params,
    *,
    client_id: str,
    retries: int,
    refreshed: bool,
):
    await asyncio.sleep(RATE_DELAY)
    async with http.get(url, headers=headers, params=params) as resp:
        if resp.status == 429:
            try:
                retry_after = max(1, int(resp.headers.get("Retry-After", "10")))
            except (TypeError, ValueError):
                retry_after = 10
            if retries >= 5:
                raise TwitchClipAPIError("Twitch rate limit retries exhausted")
            log.warning("Rate limited, sleeping %ds", retry_after)
            await asyncio.sleep(retry_after)
            return await _api_get_retry(
                http,
                url,
                headers,
                params,
                client_id=client_id,
                retries=retries + 1,
                refreshed=refreshed,
            )

        if resp.status == 401:
            if refreshed:
                raise TwitchClipAPIError("Twitch API still returned 401 after token refresh")
            log.warning("Token expired (401), refreshing…")
            new_token = await _refresh_token()
            if new_token:
                headers.clear()
                headers.update(_build_headers(client_id, new_token))
                log.info("Token refreshed, retrying request")
                return await _api_get_retry(
                    http,
                    url,
                    headers,
                    params,
                    client_id=client_id,
                    retries=retries + 1,
                    refreshed=True,
                )
            raise TwitchClipAPIError("Twitch token refresh failed")

        if resp.status != 200:
            if resp.status >= 500 and retries < 3:
                await asyncio.sleep(2**retries)
                return await _api_get_retry(
                    http,
                    url,
                    headers,
                    params,
                    client_id=client_id,
                    retries=retries + 1,
                    refreshed=refreshed,
                )
            raise TwitchClipAPIError(f"Twitch API returned HTTP {resp.status} for {url}")
        data = await resp.json()
        if not isinstance(data, dict) or not isinstance(data.get("data"), list):
            raise TwitchClipAPIError(f"Twitch API returned invalid payload for {url}")
        return data


async def _resolve_broadcaster_id(
    http,
    headers,
    *,
    client_id: str,
    channel_login: str = BROADCASTER_LOGIN,
) -> str:
    cached = _broadcaster_id_cache.get(channel_login.casefold())
    if cached:
        return cached
    data = await _api_get(
        http, f"{TWITCH_API}/users", headers, {"login": channel_login},
        client_id=client_id,
    )
    rows = data.get("data") or []
    if not rows:
        raise RuntimeError(f"Broadcaster {channel_login!r} not found on Twitch")
    broadcaster_id = str(rows[0]["id"])
    _broadcaster_id_cache[channel_login.casefold()] = broadcaster_id
    return broadcaster_id


async def _fetch_clips_for_window(
    http, headers, broadcaster_id: str, started_at: datetime, ended_at: datetime,
    *, client_id: str,
) -> list[dict]:
    if ended_at <= started_at:
        return []
    if ended_at - started_at > timedelta(days=6):
        clips_by_id: dict[str, dict] = {}
        cursor = started_at
        while cursor < ended_at:
            window_end = min(cursor + timedelta(days=6), ended_at)
            batch = await _fetch_clips_for_window(
                http,
                headers,
                broadcaster_id,
                cursor,
                window_end,
                client_id=client_id,
            )
            for clip in batch:
                clip_id = str(clip.get("id") or "")
                if clip_id:
                    clips_by_id[clip_id] = clip
            cursor = window_end
        return list(clips_by_id.values())

    clips: list[dict] = []
    cursor: str | None = None

    while True:
        params: dict = {
            "broadcaster_id": broadcaster_id,
            "started_at": _to_iso(started_at),
            "ended_at": _to_iso(ended_at),
            "first": CLIPS_PAGE_SIZE,
        }
        if cursor:
            params["after"] = cursor

        data = await _api_get(
            http, f"{TWITCH_API}/clips", headers, params, client_id=client_id,
        )
        batch = data.get("data") or []
        clips.extend(batch)

        pagination = data.get("pagination") or {}
        cursor = pagination.get("cursor")
        if not cursor or not batch:
            break

    return clips


async def _fetch_all_clips_by_streams(
    http, headers, broadcaster_id: str, streams: list[Stream],
    *, client_id: str,
) -> list[dict]:
    seen: set[str] = set()
    all_clips: list[dict] = []
    now = _utcnow()

    for idx, stream in enumerate(streams):
        started = stream.started_at
        if idx + 1 < len(streams):
            ended = streams[idx + 1].started_at
        else:
            ended = stream.ended_at or now

        window_clips = await _fetch_clips_for_window(
            http, headers, broadcaster_id, started, ended, client_id=client_id,
        )

        new_count = 0
        for clip in window_clips:
            cid = clip["id"]
            if cid not in seen:
                seen.add(cid)
                all_clips.append(clip)
                new_count += 1

        log.info(
            "Stream %d/%d (%s): %d clips (%d new)",
            idx + 1,
            len(streams),
            started.strftime("%Y-%m-%d"),
            len(window_clips),
            new_count,
        )

    return all_clips


async def _fetch_games(http, headers, twitch_game_ids: set[str], *, client_id: str) -> dict[str, str]:
    id_to_name: dict[str, str] = {}
    ids = [gid for gid in twitch_game_ids if gid and gid != "0"]

    for i in range(0, len(ids), GAMES_PAGE_SIZE):
        batch = ids[i : i + GAMES_PAGE_SIZE]
        params = [("id", gid) for gid in batch]
        data = await _api_get(
            http, f"{TWITCH_API}/games", headers, params, client_id=client_id,
        )
        for row in data.get("data") or []:
            id_to_name[str(row["id"])] = row["name"]

    return id_to_name


async def _get_or_create_user(session, *, twitch_user_id: str, login: str, display_name: str) -> User:
    return await get_or_create_user_by_twitch_id(
        session,
        twitch_user_id=twitch_user_id,
        login=login,
        display_name=display_name,
    )


_game_cache: dict[str, Game] = {}


async def _get_or_create_game(session, twitch_game_id: str, game_name: str) -> int | None:
    if not game_name:
        return None
    game = await get_or_create_game(session, _game_cache, game_name, source="twitch_api")
    return game.id


async def _find_stream_for_clip(
    session, clip_dt: datetime, twitch_video_id: str | None = None
) -> int | None:
    if twitch_video_id:
        from database.models import StreamRecording

        result = await session.execute(
            select(StreamRecording.stream_id)
            .where(
                StreamRecording.source == "twitch",
                StreamRecording.twitch_video_id == twitch_video_id,
            )
            .order_by(StreamRecording.id.desc())
            .limit(1)
        )
        stream_id = result.scalar_one_or_none()
        if stream_id is not None:
            return int(stream_id)

    result = await session.execute(
        select(Stream.id)
        .where(Stream.started_at <= clip_dt)
        .where(
            (Stream.ended_at >= clip_dt) | (Stream.ended_at.is_(None))
        )
        .order_by(Stream.started_at.desc())
        .limit(1)
    )
    row = result.first()
    if row:
        return row[0]

    # Clips created shortly after a broadcast can still belong to that stream.
    result = await session.execute(
        select(Stream.id)
        .where(Stream.ended_at <= clip_dt)
        .where(Stream.ended_at >= clip_dt - timedelta(days=1))
        .order_by(Stream.ended_at.desc())
        .limit(1)
    )
    row = result.first()
    return row[0] if row else None


async def _backfill_game_ids(http, headers, *, client_id: str) -> int:
    """For existing clips with game_id IS NULL, fetch game from Twitch API by clip external_id."""
    updated = 0

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Clip).where(Clip.game_id.is_(None))
        )
        clips_to_fix = list(result.scalars().all())

    if not clips_to_fix:
        log.info("No clips with missing game_id")
        return 0

    log.info("Backfilling game_id for %d clips…", len(clips_to_fix))

    # Twitch /clips?id=X returns clip with game_id
    for i in range(0, len(clips_to_fix), CLIPS_PAGE_SIZE):
        batch = clips_to_fix[i : i + CLIPS_PAGE_SIZE]
        params = [("id", c.external_id) for c in batch]

        data = await _api_get(
            http, f"{TWITCH_API}/clips", headers, params, client_id=client_id,
        )
        api_clips = {c["id"]: c for c in (data.get("data") or [])}

        # collect game_ids for batch
        twitch_gids = {
            c.get("game_id", "")
            for c in api_clips.values()
            if c.get("game_id")
        }
        game_name_map = await _fetch_games(http, headers, twitch_gids, client_id=client_id)

        async with AsyncSessionLocal() as session:
            for clip_record in batch:
                api_clip = api_clips.get(clip_record.external_id)
                if not api_clip:
                    continue

                twitch_gid = api_clip.get("game_id", "")
                game_name = game_name_map.get(str(twitch_gid)) if twitch_gid else None
                if not game_name:
                    continue

                game_id = await _get_or_create_game(session, str(twitch_gid), game_name)
                if game_id:
                    clip_record.game_id = game_id
                    session.add(clip_record)
                    updated += 1

            await session.commit()

        log.info("Backfill batch %d–%d done", i + 1, min(i + CLIPS_PAGE_SIZE, len(clips_to_fix)))

    log.info("Backfill complete: updated=%d", updated)
    return updated


async def _persist_clip_batch(
    http,
    clips: list[dict],
    *,
    client_id: str,
    headers: dict,
    resolve_games: bool = True,
) -> int:
    """Upsert Twitch metadata for a completed clip query."""
    if not clips:
        return 0

    twitch_game_ids = {
        str(clip.get("game_id") or "")
        for clip in clips
        if clip.get("game_id")
    }
    game_name_map = (
        await _fetch_games(
            http,
            headers,
            twitch_game_ids,
            client_id=client_id,
        )
        if resolve_games
        else {}
    )
    now = _utcnow()
    inserted = 0
    async with AsyncSessionLocal() as session:
        for clip in clips:
            external_id = str(clip.get("id") or "").strip()
            created_raw = clip.get("created_at")
            if not external_id or not created_raw:
                continue
            clip_dt = _parse_dt(created_raw)
            twitch_video_id = str(clip.get("video_id") or "").strip() or None

            existing_result = await session.execute(
                select(Clip).where(Clip.external_id == external_id).limit(1)
            )
            clip_record = existing_result.scalar_one_or_none()
            stream_id = await _find_stream_for_clip(
                session, clip_dt, twitch_video_id
            )
            if stream_id is None and clip_record is not None:
                stream_id = int(clip_record.stream_id)
            if stream_id is None:
                continue

            twitch_game_id = str(clip.get("game_id") or "")
            game_name = game_name_map.get(twitch_game_id)
            game_id = (
                await _get_or_create_game(session, twitch_game_id, game_name)
                if game_name
                else None
            )

            creator_user_id = (
                int(clip_record.creator_user_id)
                if clip_record is not None and clip_record.creator_user_id is not None
                else None
            )
            creator_login = str(clip.get("creator_name") or "").strip().lower()
            creator_id = str(clip.get("creator_id") or "").strip()
            if creator_user_id is None and creator_login and creator_id:
                user = await _get_or_create_user(
                    session,
                    twitch_user_id=creator_id,
                    login=creator_login,
                    display_name=str(clip.get("creator_name") or creator_login),
                )
                creator_user_id = int(user.id)

            values = {
                "title": str(clip.get("title") or ""),
                "url": str(clip.get("url") or ""),
                "thumbnail_url": clip.get("thumbnail_url"),
                "twitch_video_id": twitch_video_id,
                "created_at": clip_dt,
                "duration_seconds": int(float(clip.get("duration") or 0)),
                "views_count": int(clip.get("view_count") or 0),
                "synced_at": now,
            }
            if clip_record is None:
                clip_record = Clip(
                    external_id=external_id,
                    stream_id=stream_id,
                    game_id=game_id,
                    creator_user_id=creator_user_id,
                    **values,
                )
                session.add(clip_record)
                inserted += 1
            else:
                clip_record.stream_id = stream_id
                if game_id is not None:
                    clip_record.game_id = game_id
                if creator_user_id is not None:
                    clip_record.creator_user_id = creator_user_id
                for field, value in values.items():
                    if field in {"thumbnail_url", "twitch_video_id"} and value is None:
                        continue
                    setattr(clip_record, field, value)
                session.add(clip_record)
        await session.commit()
    return inserted


async def _fetch_and_persist_clip_window(
    http,
    headers: dict,
    broadcaster_id: str,
    started_at: datetime,
    ended_at: datetime,
    *,
    client_id: str,
) -> int:
    clips = await _fetch_clips_for_window(
        http,
        headers,
        broadcaster_id,
        started_at,
        ended_at,
        client_id=client_id,
    )
    return await _persist_clip_batch(
        http, clips, client_id=client_id, headers=headers
    )


async def sync_clips_window(started_at: datetime, ended_at: datetime) -> int:
    """Incrementally sync a bounded time window; returns newly inserted clips."""
    from config import settings as app_settings

    if not app_settings.CLIENT_ID or not app_settings.TWITCH_ACCESS_TOKEN:
        raise TwitchClipAPIError("CLIENT_ID or TWITCH_ACCESS_TOKEN is not configured")

    access_token = await _ensure_valid_token(app_settings.TWITCH_ACCESS_TOKEN)
    headers = _build_headers(app_settings.CLIENT_ID, access_token)
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as http:
        channel_login = app_settings.TWITCH_PRIMARY_CHANNEL or BROADCASTER_LOGIN
        broadcaster_id = await _resolve_broadcaster_id(
            http,
            headers,
            client_id=app_settings.CLIENT_ID,
            channel_login=channel_login,
        )
        # Keep each Helix range comfortably below Twitch's maximum window.
        inserted = 0
        cursor = started_at
        while cursor < ended_at:
            window_end = min(cursor + timedelta(days=6), ended_at)
            inserted += await _fetch_and_persist_clip_window(
                http,
                headers,
                broadcaster_id,
                cursor,
                window_end,
                client_id=app_settings.CLIENT_ID,
            )
            cursor = window_end
        return inserted


async def refresh_clip_metrics(external_ids: list[str]) -> int:
    """Refresh metadata for a bounded list of existing Twitch clips."""
    from config import settings as app_settings

    ids = list(dict.fromkeys(str(value).strip() for value in external_ids if value))
    if not ids:
        return 0
    if not app_settings.CLIENT_ID or not app_settings.TWITCH_ACCESS_TOKEN:
        raise TwitchClipAPIError("CLIENT_ID or TWITCH_ACCESS_TOKEN is not configured")

    access_token = await _ensure_valid_token(app_settings.TWITCH_ACCESS_TOKEN)
    headers = _build_headers(app_settings.CLIENT_ID, access_token)
    timeout = aiohttp.ClientTimeout(total=45)
    updated = 0
    checked_at = _utcnow()
    async with aiohttp.ClientSession(timeout=timeout) as http:
        for offset in range(0, len(ids), CLIPS_PAGE_SIZE):
            batch = ids[offset : offset + CLIPS_PAGE_SIZE]
            params = [("id", external_id) for external_id in batch]
            data = await _api_get(
                http,
                f"{TWITCH_API}/clips",
                headers,
                params,
                client_id=app_settings.CLIENT_ID,
            )
            clips = data.get("data") or []
            if clips:
                await _persist_clip_batch(
                    http,
                    clips,
                    client_id=app_settings.CLIENT_ID,
                    headers=headers,
                    resolve_games=False,
                )
                updated += len(clips)
        # A successful Twitch response may omit a removed/private clip. Record
        # that it was checked so the same stale IDs do not occupy every batch.
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(Clip)
                .where(Clip.external_id.in_(ids))
                .values(synced_at=checked_at)
            )
            await session.commit()
    return updated


async def sync_clips():
    from config.settings import CLIENT_ID, TWITCH_ACCESS_TOKEN, TWITCH_PRIMARY_CHANNEL

    if not CLIENT_ID or not TWITCH_ACCESS_TOKEN:
        log.error("CLIENT_ID or TWITCH_ACCESS_TOKEN not set in .env")
        return

    # Refresh token at start to ensure it's valid
    access_token = await _ensure_valid_token(TWITCH_ACCESS_TOKEN)
    headers = _build_headers(CLIENT_ID, access_token)

    async with aiohttp.ClientSession() as http:
        channel_login = TWITCH_PRIMARY_CHANNEL or BROADCASTER_LOGIN
        broadcaster_id = await _resolve_broadcaster_id(
            http,
            headers,
            client_id=CLIENT_ID,
            channel_login=channel_login,
        )
        log.info("Resolved %s → broadcaster_id=%s", channel_login, broadcaster_id)

        # --- Phase 1: fetch clips from Twitch ---
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(Stream).where(Stream.started_at.isnot(None)).order_by(Stream.started_at)
            )
            streams = list(result.scalars().all())

        if not streams:
            log.error("No streams found in DB")
            return

        log.info("Loaded %d streams from DB", len(streams))

        clips = await _fetch_all_clips_by_streams(
            http, headers, broadcaster_id, streams, client_id=CLIENT_ID,
        )
        log.info("Total unique clips fetched: %d", len(clips))

        if not clips:
            return

        # --- Phase 2: resolve game names ---
        twitch_game_ids = {c.get("game_id", "") for c in clips if c.get("game_id")}
        game_name_map = await _fetch_games(http, headers, twitch_game_ids, client_id=CLIENT_ID)
        log.info("Resolved %d game names from Twitch API", len(game_name_map))

        # --- Phase 3: write to DB ---
        inserted = 0
        updated_clips = 0
        skipped_no_stream = 0
        skipped_duplicate = 0

        async with AsyncSessionLocal() as session:
            for clip in clips:
                external_id = clip["id"]
                clip_dt = _parse_dt(clip["created_at"])

                existing = await session.execute(
                    select(Clip).where(Clip.external_id == external_id).limit(1)
                )
                clip_record = existing.scalar_one_or_none()
                if clip_record is not None:
                    changed = False
                    new_title = clip.get("title", "")
                    new_views = clip.get("view_count", 0)
                    new_video_id = str(clip.get("video_id") or "").strip() or None
                    new_thumbnail = clip.get("thumbnail_url")
                    new_duration = int(float(clip.get("duration", 0)))
                    for field, value in (
                        ("title", new_title),
                        ("views_count", new_views),
                        ("twitch_video_id", new_video_id),
                        ("thumbnail_url", new_thumbnail),
                        ("duration_seconds", new_duration),
                    ):
                        if value is not None and getattr(clip_record, field) != value:
                            setattr(clip_record, field, value)
                            changed = True
                    clip_record.synced_at = _utcnow()
                    if changed:
                        session.add(clip_record)
                        updated_clips += 1
                    else:
                        skipped_duplicate += 1
                    continue

                stream_id = await _find_stream_for_clip(
                    session, clip_dt, str(clip.get("video_id") or "").strip() or None
                )
                if stream_id is None:
                    skipped_no_stream += 1
                    continue

                twitch_gid = clip.get("game_id", "")
                game_name = game_name_map.get(str(twitch_gid)) if twitch_gid else None
                game_id = await _get_or_create_game(session, str(twitch_gid), game_name)

                creator_user_id = None
                creator_login = clip.get("creator_name", "").lower()
                creator_display = clip.get("creator_name", "")
                creator_tid = clip.get("creator_id", "")
                if creator_login:
                    user = await _get_or_create_user(
                        session,
                        twitch_user_id=str(creator_tid),
                        login=creator_login,
                        display_name=creator_display,
                    )
                    creator_user_id = user.id

                session.add(
                    Clip(
                        external_id=external_id,
                        stream_id=stream_id,
                        game_id=game_id,
                        creator_user_id=creator_user_id,
                        title=clip.get("title", ""),
                        url=clip["url"],
                        thumbnail_url=clip.get("thumbnail_url"),
                        twitch_video_id=str(clip.get("video_id") or "").strip() or None,
                        created_at=clip_dt,
                        duration_seconds=int(float(clip.get("duration", 0))),
                        views_count=clip.get("view_count", 0),
                        synced_at=_utcnow(),
                    )
                )
                inserted += 1

                if inserted % 100 == 0:
                    await session.commit()
                    log.info("Committed %d clips…", inserted)

            await session.commit()

        log.info(
            "Sync done: inserted=%d, updated=%d, skipped_duplicate=%d, skipped_no_stream=%d",
            inserted, updated_clips, skipped_duplicate, skipped_no_stream,
        )

        # --- Phase 4: backfill missing game_ids from previous runs ---
        await _backfill_game_ids(http, headers, client_id=CLIENT_ID)


async def _ensure_valid_token(token: str) -> str:
    from services.token_service import ensure_valid_token
    return await ensure_valid_token()


if __name__ == "__main__":
    asyncio.run(sync_clips())
