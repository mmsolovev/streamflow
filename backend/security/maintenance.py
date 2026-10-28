"""Background maintenance jobs for the web backend."""
from __future__ import annotations

import asyncio
from datetime import datetime

from sqlalchemy import delete

from config.settings import TWITCH_BAN_SYNC_INTERVAL_SECONDS
from database.db import AsyncSessionLocal
from database.models import WebSession
from backend.config import get_backend_settings
from services.twitch_ban_service import sync_active_session_bans


async def cleanup_expired_sessions() -> int:
    """Delete expired web sessions and return the number of removed rows."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            delete(WebSession).where(WebSession.expires_at <= datetime.utcnow())
        )
        await session.commit()
        return int(result.rowcount or 0)


async def cleanup_expired_sessions_loop() -> None:
    """Run session cleanup until the application shuts down."""
    interval = max(60, get_backend_settings().backend_session_cleanup_interval_seconds)
    while True:
        try:
            await cleanup_expired_sessions()
        except asyncio.CancelledError:
            raise
        except Exception:
            # Maintenance must not terminate the API process after a transient
            # database outage. The next interval retries the cleanup.
            pass
        await asyncio.sleep(interval)


async def sync_twitch_bans_loop() -> None:
    """Periodically refresh Twitch bans for users with active web sessions."""
    interval = max(300, TWITCH_BAN_SYNC_INTERVAL_SECONDS)
    while True:
        try:
            await sync_active_session_bans()
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(interval)
