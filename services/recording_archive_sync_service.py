"""Периодическая синхронизация доступности Twitch VOD."""

from __future__ import annotations

import asyncio

import config.settings as settings
from utils.logger import get_logger

logger = get_logger("recording.archive_sync")


class RecordingArchiveSyncWorker:
    """Синхронизирует архив Twitch при старте бота и по заданному интервалу."""

    def __init__(self, interval_seconds: int | None = None):
        self.interval_seconds = max(
            int(interval_seconds or settings.TWITCH_VOD_ARCHIVE_SYNC_INTERVAL_SECONDS),
            300,
        )
        self._task: asyncio.Task | None = None
        self._stopping = False

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._stopping = False
        self._task = asyncio.get_running_loop().create_task(
            self._run(), name="twitch-vod-archive-sync"
        )
        logger.info(
            "Twitch VOD archive sync started (interval=%ss)",
            self.interval_seconds,
        )

    async def stop(self) -> None:
        self._stopping = True
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    async def _run(self) -> None:
        from pipeline.orchestrator.sync_vods import run as sync_vods

        while not self._stopping:
            delay = self.interval_seconds
            try:
                completed = await sync_vods()
                if not completed:
                    logger.warning("Archive sync skipped; verify Twitch API credentials")
                    delay = min(self.interval_seconds, 300)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Twitch VOD archive synchronization failed")
                delay = min(self.interval_seconds, 300)
            await asyncio.sleep(delay)
