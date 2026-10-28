"""Синхронизация Twitch-банов канала с локальными ограничениями."""
from __future__ import annotations

import time
from datetime import datetime

import aiohttp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import get_backend_settings
from backend.security.twitch_tokens import get_streamer_access_token
from config.settings import (
    RECOMMENDATIONS_STREAMER_LOGIN,
    TWITCH_BAN_CHECK_TTL_SECONDS,
    TWITCH_BAN_FAIL_OPEN,
)
from database.db import AsyncSessionLocal
from database.models import User, UserRestriction, WebSession
from services.authz_service import Restrictions, load_restrictions
from services.streamer_service import resolve_primary_streamer_id


TWITCH_BANNED_URL = "https://api.twitch.tv/helix/moderation/banned"

_last_checked: dict[int, float] = {}


def _is_fresh(user_id: int) -> bool:
    checked_at = _last_checked.get(user_id)
    return bool(checked_at and checked_at > time.monotonic())


async def check_twitch_ban(twitch_user_id: str) -> bool | None:
    """Return True/False, or None when Twitch is unavailable (fail-open)."""
    if not twitch_user_id:
        return None
    settings = get_backend_settings()
    if not settings.twitch_client_id:
        return None

    async with AsyncSessionLocal() as session:
        try:
            broadcaster_id = await resolve_primary_streamer_id(session)
            access_token = await get_streamer_access_token(session, broadcaster_id)
            await session.commit()
        except Exception:
            await session.rollback()
            return None

    params = {"broadcaster_id": str(broadcaster_id), "user_id": str(twitch_user_id)}
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Client-Id": settings.twitch_client_id,
    }
    timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as client:
            async with client.get(TWITCH_BANNED_URL, params=params, headers=headers) as response:
                body = await response.json(content_type=None)
                if response.status != 200:
                    return None
                return bool(body.get("data"))
    except (aiohttp.ClientError, TimeoutError):
        return None


async def sync_user_twitch_ban(
    user_id: int,
    twitch_user_id: str | None,
    *,
    force: bool = False,
) -> Restrictions:
    """Refresh one user's Twitch ban state and persist the restriction row."""
    if not force and _is_fresh(user_id):
        async with AsyncSessionLocal() as session:
            return await load_restrictions(session, user_id)

    banned = await check_twitch_ban(twitch_user_id or "")
    check_failed = banned is None
    if check_failed:
        _last_checked[user_id] = time.monotonic() + TWITCH_BAN_CHECK_TTL_SECONDS
        if TWITCH_BAN_FAIL_OPEN:
            async with AsyncSessionLocal() as session:
                return await load_restrictions(session, user_id)
        banned = True

    now = datetime.utcnow()
    channel = RECOMMENDATIONS_STREAMER_LOGIN.strip().casefold()
    async with AsyncSessionLocal() as session:
        active = (
            await session.execute(
                select(UserRestriction).where(
                    UserRestriction.user_id == user_id,
                    UserRestriction.kind == "twitch_ban",
                    UserRestriction.channel == channel,
                    UserRestriction.lifted_at.is_(None),
                )
            )
        ).scalar_one_or_none()

        reason = "Twitch ban check unavailable" if check_failed else "Twitch ban"
        if banned:
            if active is None:
                active = UserRestriction(
                    user_id=user_id,
                    kind="twitch_ban",
                    channel=channel,
                    reason=reason,
                    source="twitch_api",
                    created_at=now,
                    checked_at=now,
                )
                session.add(active)
            else:
                active.checked_at = now
                active.reason = reason
        elif active is not None:
            active.lifted_at = now
            active.checked_at = now

        await session.commit()
        restrictions = await load_restrictions(session, user_id)

    _last_checked[user_id] = time.monotonic() + TWITCH_BAN_CHECK_TTL_SECONDS
    return restrictions


async def sync_active_session_bans() -> int:
    """Periodic job: refresh Twitch ban state for users with live web sessions."""
    now = datetime.utcnow()
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(User.id, User.twitch_user_id)
                .join(WebSession, WebSession.user_id == User.id)
                .where(WebSession.expires_at > now)
                .distinct()
            )
        ).all()

    synced = 0
    for user_id, twitch_user_id in rows:
        await sync_user_twitch_ban(int(user_id), twitch_user_id, force=True)
        synced += 1
    return synced
