from __future__ import annotations

"""
IGDB authorization helpers.

This module only contains shared Twitch/IGDB auth primitives.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from weakref import WeakKeyDictionary

import aiohttp

from config.settings import IGDB_CLIENT_ID, IGDB_CLIENT_SECRET
from utils.logger import get_logger


TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"


class _IGDBLoopState:
    def __init__(self, *, token: str | None, token_expires_at: datetime | None, token_lock: asyncio.Lock):
        self.token = token
        self.token_expires_at = token_expires_at
        self.token_lock = token_lock


_state_by_loop: "WeakKeyDictionary[asyncio.AbstractEventLoop, _IGDBLoopState]" = WeakKeyDictionary()


def _get_state() -> _IGDBLoopState:
    loop = asyncio.get_running_loop()
    state = _state_by_loop.get(loop)
    if state is not None:
        return state

    state = _IGDBLoopState(token=None, token_expires_at=None, token_lock=asyncio.Lock())
    _state_by_loop[loop] = state
    return state


async def _get_token(state: _IGDBLoopState, *, force_refresh: bool = False) -> str:
    logger = get_logger("igdb.token")
    async with state.token_lock:
        if (not force_refresh) and state.token and state.token_expires_at and state.token_expires_at > datetime.utcnow():
            return state.token

        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            params = {
                "client_id": IGDB_CLIENT_ID,
                "client_secret": IGDB_CLIENT_SECRET,
                "grant_type": "client_credentials",
            }
            async with session.post(TWITCH_TOKEN_URL, params=params) as resp:
                data = await resp.json()

        token = str(data.get("access_token") or "")
        expires_in = int(data.get("expires_in") or 0)
        if not token or expires_in <= 0:
            logger.warning("Failed to fetch IGDB token", extra={"data": data})
            raise RuntimeError("IGDB token fetch failed")

        state.token = token
        state.token_expires_at = datetime.utcnow() + timedelta(seconds=expires_in - 30)
        return token


async def get_igdb_token(*, force_refresh: bool = False) -> str:
    state = _get_state()
    return await _get_token(state, force_refresh=force_refresh)


async def build_igdb_auth_headers(*, force_refresh: bool = False) -> dict[str, str]:
    token = await get_igdb_token(force_refresh=force_refresh)
    return {
        "Client-ID": IGDB_CLIENT_ID,
        "Authorization": f"Bearer {token}",
    }

__all__ = ["build_igdb_auth_headers", "get_igdb_token"]

