"""Database backed Twitch token rotation."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import TwitchAuthorization, TwitchStreamerAuthorization
from backend.config import get_backend_settings
from backend.security.token_crypto import (
    KEY_VERSION,
    decrypt_stored_token,
    encrypt_token,
)
from backend.security.twitch_oauth import refresh_access_token


def _access_token(authorization) -> str | None:
    return decrypt_stored_token(authorization.access_token_encrypted)


def _refresh_token(authorization) -> str | None:
    return decrypt_stored_token(authorization.refresh_token_encrypted)


async def _rotate(session: AsyncSession, authorization) -> str:
    """Обновить пару токенов у строки авторизации и вернуть новый access token.

    Общая логика для обычного и «стримерского» токена: обе строки имеют
    одинаковый набор полей (access_token/refresh_token/expires_at/...).
    """
    now = datetime.utcnow()
    settings = get_backend_settings()
    refresh_before = now + timedelta(seconds=settings.twitch_token_refresh_skew_seconds)
    if authorization.expires_at is None or authorization.expires_at > refresh_before:
        access_token = _access_token(authorization)
        if not access_token:
            raise RuntimeError("Twitch access token is not available")
        return access_token

    refresh_token = _refresh_token(authorization)
    if not refresh_token:
        raise RuntimeError("Twitch refresh token is not available")

    token_data = await refresh_access_token(refresh_token)
    expires_in = token_data.get("expires_in")
    authorization.access_token_encrypted = encrypt_token(token_data["access_token"])
    authorization.refresh_token_encrypted = encrypt_token(
        token_data.get("refresh_token") or refresh_token
    )
    authorization.key_version = KEY_VERSION
    authorization.expires_at = now + timedelta(seconds=int(expires_in)) if expires_in else None
    authorization.last_refresh_at = now
    authorization.updated_at = now
    await session.flush()
    return token_data["access_token"]


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
    return await _rotate(session, authorization)


async def get_streamer_access_token(session: AsyncSession, user_id: int) -> str:
    """As `get_twitch_access_token`, but for the streamer (elevated) token.

    Читает таблицу `twitch_streamer_authorizations`. Токен нужен боту для
    операций, доступных только аккаунту стримера (например, баллы канала).
    """
    authorization = (
        await session.execute(
            select(TwitchStreamerAuthorization)
            .where(TwitchStreamerAuthorization.user_id == user_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if authorization is None:
        raise LookupError("Streamer Twitch authorization not found")
    return await _rotate(session, authorization)
