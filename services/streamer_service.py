"""Резолвинг основного стримера по логину вместо жёсткого users.id."""
from __future__ import annotations

import time

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from backend.config import get_backend_settings
from config.settings import RECOMMENDATIONS_STREAMER_LOGIN, SHEETS_STREAMER_ID
from database.db import AsyncSessionLocal, SessionLocal
from database.models import User, UserProfile


_CACHE_TTL_SECONDS = 300.0
_cache: tuple[float, int] | None = None


def invalidate_streamer_cache() -> None:
    global _cache
    _cache = None


def _pick_override() -> int | None:
    """Explicit env override, if configured (0/None means resolve from DB)."""
    for value in (get_backend_settings().backend_streamer_id, SHEETS_STREAMER_ID):
        if value:
            return int(value)
    return None


def _from_rows(rows) -> int | None:
    for user_id, login in rows:
        if (login or "").strip().casefold() == RECOMMENDATIONS_STREAMER_LOGIN.strip().casefold():
            return int(user_id)
    return None


def _missing() -> RuntimeError:
    return RuntimeError(
        f"Не найден основной стример {RECOMMENDATIONS_STREAMER_LOGIN!r}. "
        "Проверьте профиль пользователя или задайте SHEETS_STREAMER_ID."
    )


def resolve_primary_streamer_id_sync(session: Session | None = None) -> int:
    global _cache
    now = time.monotonic()
    if _cache and _cache[0] > now:
        return _cache[1]

    override = _pick_override()
    if override:
        _cache = (now + _CACHE_TTL_SECONDS, override)
        return override

    owns_session = session is None
    session = session or SessionLocal()
    try:
        rows = session.execute(
            select(User.id, UserProfile.login).join(
                UserProfile,
                (UserProfile.user_id == User.id) & (UserProfile.is_current.is_(True)),
            )
        ).all()
    finally:
        if owns_session:
            session.close()

    user_id = _from_rows(rows)
    if user_id is None:
        raise _missing()
    _cache = (now + _CACHE_TTL_SECONDS, user_id)
    return user_id


async def resolve_primary_streamer_id(session: AsyncSession | None = None) -> int:
    global _cache
    now = time.monotonic()
    if _cache and _cache[0] > now:
        return _cache[1]

    override = _pick_override()
    if override:
        _cache = (now + _CACHE_TTL_SECONDS, override)
        return override

    owns_session = session is None
    session = session or AsyncSessionLocal()
    try:
        rows = (
            await session.execute(
                select(User.id, UserProfile.login).join(
                    UserProfile,
                    (UserProfile.user_id == User.id) & (UserProfile.is_current.is_(True)),
                )
            )
        ).all()
    finally:
        if owns_session:
            await session.close()

    user_id = _from_rows(rows)
    if user_id is None:
        raise _missing()
    _cache = (now + _CACHE_TTL_SECONDS, user_id)
    return user_id
