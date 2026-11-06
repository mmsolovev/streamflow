"""Синхронизация `stream_recordings` с архивом Twitch.

Запуск:
    python -m pipeline.orchestrator.sync_vods

Правила:
  1. Точное совпадение: VOD `stream_id` == `streams.external_id`. Это
     единственный надёжный способ отличить записи реконнектов.
  2. Fallback по времени — только для legacy-стримов без записи (и строк
     без `external_id`): раньше связь определялась по широкому окну.
  3. Записи, которых больше нет в архиве, не удаляются: `is_available=False`.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import timedelta
from pathlib import Path

import aiohttp
from sqlalchemy import select

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import config.settings as settings
from database.db import AsyncSessionLocal
from database.models import Stream, StreamRecording
from pipeline.ingest.twitch_api import TwitchTokenExpiredError, fetch_user_id, fetch_vods
from pipeline.transform.streams_transform import build_vods_index, pick_vod_candidates
from services import recording_service

_LOG_FMT = "%(asctime)s | %(levelname)-5s | %(name)s | %(message)s"
logging.basicConfig(level=logging.INFO, format=_LOG_FMT, handlers=[logging.StreamHandler()])
_log = logging.getLogger("sync_vods")


def _vod_key(vod: dict) -> str:
    return str(vod.get("id") or "").strip()


def _vod_broadcast(vod: dict) -> str:
    return str(vod.get("stream_id") or "").strip()


def _stream_end(stream: Stream):
    if stream.ended_at:
        return stream.ended_at
    if stream.duration_minutes:
        return stream.started_at + timedelta(minutes=stream.duration_minutes)
    return stream.started_at + timedelta(hours=12)


async def _fetch_vods(http: aiohttp.ClientSession) -> list[dict]:
    token = settings.TWITCH_ACCESS_TOKEN
    client_id = settings.CLIENT_ID
    channel = settings.TWITCH_PRIMARY_CHANNEL

    if not (client_id and token and channel):
        _log.error("Missing CLIENT_ID / TWITCH_ACCESS_TOKEN / TWITCH_PRIMARY_CHANNEL")
        return []

    try:
        user_id = await fetch_user_id(
            http, client_id=client_id, access_token=token, channel_login=channel
        )
    except TwitchTokenExpiredError:
        from services.token_service import try_refresh_token

        new_token = await try_refresh_token()
        if not new_token:
            _log.error("Token refresh failed")
            return []
        settings.TWITCH_ACCESS_TOKEN = new_token
        token = new_token
        user_id = await fetch_user_id(
            http, client_id=client_id, access_token=token, channel_login=channel
        )

    vods = await fetch_vods(
        http, client_id=client_id, access_token=token, user_id=user_id
    )
    _log.info("Fetched %d VOD(s)", len(vods))
    return vods


async def run() -> None:
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as http:
        vods = await _fetch_vods(http)

    if not vods:
        _log.warning("No VODs fetched, nothing to sync.")
        return

    vods_by_date = build_vods_index(vods)
    vod_by_broadcast: dict[str, dict] = {}
    for vod in vods:
        broadcast = _vod_broadcast(vod)
        if not broadcast:
            continue
        existing = vod_by_broadcast.get(broadcast)
        # При дублях одной обработки берём самую длинную запись.
        if existing is None or (recording_service.parse_duration_minutes(
            vod.get("duration")
        ) or 0) > (recording_service.parse_duration_minutes(
            existing.get("duration")
        ) or 0):
            vod_by_broadcast[broadcast] = vod

    async with AsyncSessionLocal() as session:
        streams = (
            await session.execute(
                select(Stream)
                .where(Stream.started_at.isnot(None))
                .order_by(Stream.started_at.desc())
            )
        ).scalars().all()
        streams_by_external = {
            str(stream.external_id): stream
            for stream in streams
            if stream.external_id
        }

        # --- 1. Точное совпадение по Twitch broadcast id ------------------
        exact = 0
        used_vod_ids: set[str] = set()
        for broadcast, vod in vod_by_broadcast.items():
            stream = streams_by_external.get(broadcast)
            if stream is None:
                continue
            recording = await recording_service.upsert_from_vod(
                session, stream_id=int(stream.id), vod=vod
            )
            if recording is not None:
                exact += 1
                vod_id = _vod_key(vod)
                if vod_id:
                    used_vod_ids.add(vod_id)
                _log.info(
                    "  = VOD for stream %s (%s): %s",
                    stream.id,
                    broadcast,
                    recording.url,
                )
        _log.info("Exact broadcast matches: %d", exact)

        # --- 2. Fallback по времени для legacy-стримов ---------------------
        rec_result = await session.execute(
            select(StreamRecording.stream_id).where(
                StreamRecording.source == "twitch"
            )
        )
        streams_with_recording = {int(row[0]) for row in rec_result.all()}

        added = 0
        for stream in reversed(streams):  # хронологически, как раньше
            if stream.id in streams_with_recording:
                continue

            window_start = stream.started_at - timedelta(hours=6)
            window_end = _stream_end(stream) + timedelta(hours=6)
            candidates = pick_vod_candidates(
                vods_by_date=vods_by_date,
                stream_date=stream.started_at.date(),
            )

            for vod in candidates:
                vod_id = _vod_key(vod)
                if vod_id and vod_id in used_vod_ids:
                    continue
                fields = recording_service.fields_from_vod(vod)
                recorded_at = fields["recorded_at"]
                if recorded_at is None:
                    continue
                if not (window_start <= recorded_at <= window_end):
                    continue

                recording = await recording_service.upsert_from_vod(
                    session, stream_id=int(stream.id), vod=vod
                )
                if recording is None:
                    continue
                streams_with_recording.add(int(stream.id))
                if vod_id:
                    used_vod_ids.add(vod_id)
                added += 1
                _log.info(
                    "  + Legacy VOD for stream %s (%s): %s",
                    stream.id,
                    stream.started_at.date(),
                    recording.url,
                )
                break

        _log.info("Legacy time-based additions: %d", added)

        # --- 3. Истёкшие записи: скрыть, но не удалять ---------------------
        hidden = await recording_service.mark_missing_unavailable(
            session,
            keep_urls={
                str(vod.get("url") or "").strip()
                for vod in vods
                if str(vod.get("url") or "").strip()
            },
            keep_video_ids={
                str(vod.get("id") or "").strip()
                for vod in vods
                if str(vod.get("id") or "").strip()
            },
        )
        _log.info("Marked unavailable: %d recording(s)", hidden)

        await session.commit()
        _log.info("Done. Committed.")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
