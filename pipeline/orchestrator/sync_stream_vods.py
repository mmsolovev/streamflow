from __future__ import annotations

"""
Orchestrator job: fetch VODs from Twitch API and sync Stream.vod_url.
"""

import aiohttp

from config.settings import TWITCH_ACCESS_TOKEN, TWITCH_CHANNEL_LOGIN, TWITCH_CLIENT_ID
from database.models import Stream
from pipeline.ingest.twitch_api import fetch_user_id, fetch_vods
from pipeline.load.load_streams import find_streams_without_vod
from pipeline.transform.vod_matching import build_vods_index, is_match, pick_vod_candidates
from .context import PipelineContext


async def run(context: PipelineContext) -> None:
    """
    Fetches VODs from Twitch API and matches them to streams in the database.
    """
    if context.db_session is None:
        raise ValueError("DB session not initialized. Use `with PipelineContext(...)`.")

    # LOAD (from DB): Find streams that need a VOD URL
    streams_to_sync = find_streams_without_vod(context.db_session)
    if not streams_to_sync:
        print("All streams already have VOD URLs. Nothing to do.")
        return

    print(f"Found {len(streams_to_sync)} streams without VOD URL.")

    # INGEST: Fetch VODs from Twitch API
    async with aiohttp.ClientSession() as session:
        print("Fetching user ID for channel...")
        user_id = await fetch_user_id(
            session,
            client_id=TWITCH_CLIENT_ID,
            access_token=TWITCH_ACCESS_TOKEN,
            channel_login=TWITCH_CHANNEL_LOGIN,
        )
        print(f"Fetching all VODs for user {user_id}...")
        vods = await fetch_vods(
            session,
            client_id=TWITCH_CLIENT_ID,
            access_token=TWITCH_ACCESS_TOKEN,
            user_id=user_id,
        )
    print(f"Fetched {len(vods)} VODs.")

    # TRANSFORM: Match streams to VODs
    vods_by_date = build_vods_index(vods)
    updated_count = 0
    for stream in streams_to_sync:
        candidates = pick_vod_candidates(vods_by_date=vods_by_date, stream_date=stream.date.date())
        for vod in candidates:
            if is_match(stream, vod):
                # LOAD (to DB): Update stream with VOD URL
                stream_orm = context.db_session.query(Stream).get(stream.id)
                if stream_orm:
                    stream_orm.vod_url = vod.get("url")
                    updated_count += 1
                break  # Move to the next stream once a match is found

    print(f"Successfully matched and updated {updated_count} streams with VOD URLs.")
