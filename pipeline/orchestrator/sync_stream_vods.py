from __future__ import annotations

"""
Orchestrator job: sync Twitch VOD URLs into streams.vod_url.

Ingest: fetch VODs list from Twitch API.
Load: match and write VOD URLs into DB.
"""

import argparse
import asyncio

import aiohttp

from config.settings import CLIENT_ID, TWITCH_ACCESS_TOKEN, TWITCH_CHANNEL
from database.db import SessionLocal
from pipeline.ingest.twitch_api import fetch_user_id, fetch_vods
from pipeline.load.sync_stream_vods import sync_stream_vod_urls


async def async_run(*, dry_run: bool = False) -> None:
    async with aiohttp.ClientSession() as http:
        user_id = await fetch_user_id(
            http,
            client_id=CLIENT_ID,
            access_token=TWITCH_ACCESS_TOKEN,
            channel_login=TWITCH_CHANNEL,
        )
        vods = await fetch_vods(
            http,
            client_id=CLIENT_ID,
            access_token=TWITCH_ACCESS_TOKEN,
            user_id=user_id,
        )

    print(f"Fetched VODs: {len(vods)}")

    session = SessionLocal()
    try:
        stats = sync_stream_vod_urls(session, vods)
        if dry_run:
            session.rollback()
        else:
            session.commit()
    finally:
        session.close()

    print(f"Removed outdated VODs: {stats.removed_outdated}")
    print(f"Matched new VODs: {stats.matched_new}")
    print("Dry run: yes" if dry_run else "Dry run: no")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Twitch VOD URLs into streams.vod_url.")
    parser.add_argument("--dry-run", action="store_true", help="Do not write changes to the database.")
    args = parser.parse_args()
    asyncio.run(async_run(dry_run=bool(args.dry_run)))


if __name__ == "__main__":
    main()

