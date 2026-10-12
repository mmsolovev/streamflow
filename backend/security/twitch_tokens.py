"""Database backed Twitch token rotation."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import TwitchAuthorization
from backend.config import get_backend_settings
from backend.security.twitch_oauth import refresh_access_token


async def get_twitch_access_token(session: AsyncSession, user_id: int) -> str:
    """Return a usable access token, rotating it shortly before expiry.

    The row lock makes concurrent requests in multiple workers re-check the
    newly stored expiry before making another refresh request.
    """
    authorization = (
        await session.execute(
            select(TwitchAuthorization)
            .where(TwitchAuthorization.user_id == user_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if authorization is None:
        raise LookupError("Twitch authorization not found")

    now = datetime.utcnow()
    settings = get_backend_settings()
    refresh_before = now + timedelta(seconds=settings.twitch_token_refresh_skew_seconds)
    if authorization.expires_at is None or authorization.expires_at > refresh_before:
        return authorization.access_token

    if not authorization.refresh_token:
        raise RuntimeError("Twitch refresh token is not available")

    token_data = await refresh_access_token(authorization.refresh_token)
    expires_in = token_data.get("expires_in")
    authorization.access_token = token_data["access_token"]
    authorization.refresh_token = token_data.get("refresh_token") or authorization.refresh_token
    authorization.expires_at = now + timedelta(seconds=int(expires_in)) if expires_in else None
    authorization.last_refresh_at = now
    authorization.updated_at = now
    await session.flush()
    return authorization.access_token
