"""
One-time script: enrich existing users with data from the Twitch API.

Fills twitch_user_id, profile_image_url, display_name, twitch_url, and is_streamer
for users that currently only have login + display_name (in user_profiles).

Usage:
    python database/enrich_users.py

Requirements:
    - PostgreSQL running with users/user_profiles tables populated
    - CLIENT_ID and TWITCH_ACCESS_TOKEN configured in .env
"""

import asyncio
import logging
from datetime import datetime, timezone

import aiohttp
from sqlalchemy import select, or_

from database.db import AsyncSessionLocal
from database.models import User, UserProfile

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

TWITCH_API = "https://api.twitch.tv/helix"
BATCH_SIZE = 100  # Twitch /users accepts up to 100 logins per request


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def enrich_users():
    from config.settings import CLIENT_ID, TWITCH_ACCESS_TOKEN

    if not CLIENT_ID or not TWITCH_ACCESS_TOKEN:
        log.error("CLIENT_ID or TWITCH_ACCESS_TOKEN not set in .env")
        return

    headers = {
        "Client-ID": CLIENT_ID,
        "Authorization": f"Bearer {TWITCH_ACCESS_TOKEN}",
    }

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(User, UserProfile)
            .join(UserProfile, UserProfile.user_id == User.id)
            .where(
                UserProfile.is_current.is_(True),
                or_(
                    User.twitch_user_id.is_(None),
                    UserProfile.profile_image_url.is_(None),
                    UserProfile.twitch_url.is_(None),
                ),
            )
        )
        pairs = result.all()

    if not pairs:
        log.info("No users need enrichment")
        return

    log.info("Found %d users to enrich", len(pairs))

    enriched = 0
    not_found = 0

    async with aiohttp.ClientSession() as http:
        for i in range(0, len(pairs), BATCH_SIZE):
            batch = pairs[i : i + BATCH_SIZE]
            logins = [profile.login for _, profile in batch]

            async with http.get(
                f"{TWITCH_API}/users",
                headers=headers,
                params=[("login", login) for login in logins],
            ) as resp:
                if resp.status != 200:
                    log.warning("Twitch API returned %s, skipping batch", resp.status)
                    continue
                data = await resp.json()

            api_users = {row["login"].lower(): row for row in data.get("data") or []}

            async with AsyncSessionLocal() as session:
                for user, profile in batch:
                    row = api_users.get(profile.login.lower())
                    if row is None:
                        not_found += 1
                        log.warning("User %s not found on Twitch (deleted?)", profile.login)
                        continue

                    user.twitch_user_id = user.twitch_user_id or str(row["id"])
                    user.is_streamer = row.get("broadcaster_type") in ("partner", "affiliate")
                    profile.login = row["login"].lower()
                    profile.display_name = row["display_name"]
                    profile.profile_image_url = row.get("profile_image_url")
                    profile.twitch_url = f"https://www.twitch.tv/{profile.login}"
                    profile.updated_at = _utcnow()

                    session.add(user)
                    session.add(profile)
                    enriched += 1

                await session.commit()

            log.info("Processed batch %d–%d", i + 1, min(i + BATCH_SIZE, len(pairs)))

    log.info("Done: enriched=%d, not_found=%d", enriched, not_found)


if __name__ == "__main__":
    asyncio.run(enrich_users())