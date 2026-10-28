"""Жизненный цикл Telegram-интеграции: polling, VOD-поллер, правка анонсов.

Запускается вместе с Twitch-ботом и живёт в его же asyncio loop. Отдельный
процесс не нужен: состояние в PostgreSQL, логи общие.

Порядок работы при завершении стрима такой:
  1. `on_stream_ended` — нашли пост-анонс и поставили задачу с отложенной
     проверкой VOD (по умолчанию +11 минут: Twitch отдаёт запись не сразу);
  2. VOD-поллер раз в минуту забирает готовые задачи;
  3. нашёлся VOD — пересобираем текст подписи целиком и правим пост;
     не нашлось — WARNING в лог, пост остаётся нетронутым.

Правило переиспользования анонса (краш трансляции) живёт здесь же, в
`on_stream_ended`: если свежего анонса нет, VOD нового broadcast дописывается
в тот же пост, где уже стояла ссылка на предыдущую трансляцию.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import LinkPreviewOptions, MessageEntity
from sqlalchemy import select, update

import config.settings as settings
from database.db import AsyncSessionLocal
from database.models import (
    TelegramAnnouncement,
    TelegramAnnouncementVod,
    TelegramPostEditOperation,
)
from telegram import announcements, post_edit, post_edit_store, vod_jobs
from telegram.handlers import router as channel_router
from telegram.matcher import (
    build_channel_link_matcher,
    in_rebind_window,
    normalize_dt,
    pick_candidate,
)
from telegram.vod_service import VodLookupError, fetch_vod_for_stream
from utils.logger import get_logger


logger = get_logger("telegram.service")

COMMAND_POLL_INTERVAL_SECONDS = 5


class TelegramService:
    """Единая точка входа: старт, останов, реакция на конец стрима."""

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        token: str | None = None,
        channel_id: str | int | None = None,
    ) -> None:
        self.enabled = settings.TELEGRAM_ENABLED if enabled is None else enabled
        self.token = settings.TELEGRAM_BOT_TOKEN if token is None else token
        self.channel_id = settings.TELEGRAM_CHANNEL_ID if channel_id is None else channel_id

        self.check_delay_seconds = settings.TELEGRAM_VOD_CHECK_DELAY_SECONDS
        self.poll_interval_seconds = settings.TELEGRAM_VOD_POLL_INTERVAL_SECONDS
        self.max_attempts = settings.TELEGRAM_VOD_MAX_ATTEMPTS
        self.before_hours = settings.TELEGRAM_MATCH_WINDOW_BEFORE_HOURS
        self.after_minutes = settings.TELEGRAM_MATCH_WINDOW_AFTER_MINUTES
        self.rebind_window_minutes = settings.TELEGRAM_REBIND_WINDOW_MINUTES

        # Логин канала стримера выводится из TWITCH_PRIMARY_CHANNEL, а
        # TELEGRAM_CHANNEL_ID — это id чата для Bot API. Разные вещи.
        self.matcher = build_channel_link_matcher(
            settings.TELEGRAM_CHANNEL_URL,
            settings.TELEGRAM_LINK_DOMAINS,
        )
        self.channel_login = settings.TWITCH_PRIMARY_CHANNEL

        self.bot: Bot | None = None
        self.dispatcher: Dispatcher | None = None
        self._polling_task: asyncio.Task | None = None
        self._poller_task: asyncio.Task | None = None
        self._command_task: asyncio.Task | None = None
        self._http: aiohttp.ClientSession | None = None

    # ------------------------------------------------------------------
    # Жизненный цикл
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Поднимает polling канала и VOD-поллер. Не бросает исключений.

        Ошибка Telegram не должна ронять Twitch-бота: интеграция вспомогательная,
        и потерять праку анонса лучше, чем упасть целиком.
        """
        if not self.enabled:
            logger.info("Telegram integration disabled (TELEGRAM_ENABLED=false)")
            return

        if not self.token:
            logger.error("TELEGRAM_ENABLED=true but TELEGRAM_BOT_TOKEN is empty")
            return

        if not self.channel_id:
            logger.error("TELEGRAM_ENABLED=true but TELEGRAM_CHANNEL_ID is empty")
            return

        try:
            # parse_mode здесь НЕ задаётся намеренно: подпись уходит
            # обычным текстом с entities, и Telegram запрещает смешивать
            # entities с parse_mode. Ссылка и кастомный эмодзи задаются
            # сущностями, а не тегами.
            bot = Bot(token=self.token)
            await bot.get_me()
            self.bot = bot

            dispatcher = Dispatcher()
            dispatcher.include_router(channel_router)
            self.dispatcher = dispatcher

            # handle_signals=False обязателен: бот запускается не как
            # самостоятельное приложение, его SIGINT/SIGTERM обслуживает
            # основной процесс, иначе aiogram перехватит сигнал и положит
            # весь процесс вместе с EventSub.
            self._polling_task = asyncio.create_task(
                self._polling_loop(),
                name="telegram-polling",
            )
            self._poller_task = asyncio.create_task(
                self._vod_poller_loop(),
                name="telegram-vod-poller",
            )
            self._http = aiohttp.ClientSession()
            self._command_task = asyncio.create_task(
                self._command_loop(),
                name="telegram-post-edit-commands",
            )

            logger.info(
                "Telegram integration started for chat %s, primary channel %s",
                self.channel_id,
                self.channel_login,
            )
        except Exception:
            logger.exception("Failed to start Telegram integration")
            await self.stop()

    async def stop(self) -> None:
        for task in (self._polling_task, self._poller_task, self._command_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self._polling_task = None
        self._poller_task = None
        self._command_task = None

        if self._http and not self._http.closed:
            await self._http.close()
        self._http = None

        if self.bot:
            session = self.bot.session
            if session is not None:
                try:
                    await session.close()
                except Exception:
                    logger.debug("Failed to close Telegram bot session", exc_info=True)
        self.bot = None
        self.dispatcher = None

    async def _polling_loop(self) -> None:
        """Long polling апдейтов канала в общем loop с Twitch-ботом."""
        dispatcher, bot = self.dispatcher, self.bot
        if dispatcher is None or bot is None:
            return

        try:
            await dispatcher.start_polling(
                bot,
                handle_signals=False,
                allowed_updates=["channel_post", "edited_channel_post"],
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Telegram polling stopped with error")

    async def _vod_poller_loop(self) -> None:
        """Периодический обход очереди задач «найти VOD».

        Пауза до первой проверки задана в самой задаче (`check_at`), поэтому
        поллер сразу после старта не дёргает Twitch API заново.
        """
        try:
            while True:
                await asyncio.sleep(self.poll_interval_seconds)
                await self.process_due_jobs()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Telegram VOD poller stopped with error")

    async def _command_loop(self) -> None:
        """Обрабатывает publish/undo/restore команды из админки."""
        try:
            while True:
                await asyncio.sleep(COMMAND_POLL_INTERVAL_SECONDS)
                await self._process_commands()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Telegram post-edit command loop stopped with error")

    async def _process_commands(self) -> None:
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(TelegramAnnouncementVod)
                .where(
                    (TelegramAnnouncementVod.publish_now_requested_at.is_not(None))
                    | (TelegramAnnouncementVod.undo_requested_at.is_not(None))
                    | (TelegramAnnouncementVod.restore_requested_at.is_not(None))
                )
                .order_by(TelegramAnnouncementVod.id.asc())
                .limit(20)
                .with_for_update(skip_locked=True)
            )
            jobs = list(result.scalars().all())
            commands = [
                (
                    job.id,
                    job.publish_now_requested_at is not None,
                    job.undo_requested_at is not None,
                    job.restore_requested_at is not None,
                )
                for job in jobs
            ]
            if commands:
                await session.execute(
                    update(TelegramAnnouncementVod)
                    .where(TelegramAnnouncementVod.id.in_([item[0] for item in commands]))
                    .values(
                        publish_now_requested_at=None,
                        undo_requested_at=None,
                        restore_requested_at=None,
                        updated_at=datetime.utcnow(),
                    )
                )
                await session.commit()

        for job_id, publish_now, undo, restore in commands:
            if restore:
                await self._restore_original(job_id)
            elif undo:
                await self._undo(job_id)
            elif publish_now:
                await self._publish_now(job_id)

    async def _publish_now(self, job_id: int) -> None:
        if self._http is None or self.bot is None:
            await self._set_job_error(job_id, "Telegram service is not started")
            return

        async with AsyncSessionLocal() as session:
            job = await vod_jobs.get_by_id(session, job_id)
            if job is None or job.announcement_id is None:
                return

            vod_url = job.vod_url
            if not vod_url:
                try:
                    vod = await fetch_vod_for_stream(
                        session=self._http,
                        channel_login=self.channel_login,
                        stream_id=job.stream_id,
                        client_id=settings.CLIENT_ID,
                    )
                except Exception as exc:
                    await self._set_job_error(job_id, f"{type(exc).__name__}: {exc}")
                    return
                if vod is None or not vod.get("url"):
                    await self._set_job_error(job_id, "VOD not found in channel archive")
                    return
                vod_url = vod["url"]
                await vod_jobs.mark_resolved(
                    session,
                    job_id=job.id,
                    vod_url=vod_url,
                    duration_minutes=vod.get("duration_minutes"),
                    recorded_at=normalize_dt(vod.get("published_at") or vod.get("created_at")),
                )

            urls = await vod_jobs.resolved_urls(session, job.announcement_id)
            await self._apply_edit(session, job=job, vod_urls=urls)

    async def _undo(self, job_id: int) -> None:
        if self.bot is None:
            await self._set_job_error(job_id, "Telegram service is not started")
            return

        async with AsyncSessionLocal() as session:
            job = await vod_jobs.get_by_id(session, job_id)
            if job is None or job.announcement_id is None:
                return

            result = await session.execute(
                select(TelegramPostEditOperation)
                .where(
                    TelegramPostEditOperation.job_id == job_id,
                    TelegramPostEditOperation.status == "applied",
                )
                .order_by(TelegramPostEditOperation.id.desc())
                .limit(1)
            )
            operation = result.scalar_one_or_none()
            announcement = await announcements.get_by_id(session, job.announcement_id)
            if operation is None or announcement is None:
                await self._set_job_error(job_id, "Нет применённой операции для отмены")
                return

            if announcement.manually_edited or announcement.status == "skipped":
                await self._set_job_error(job_id, "Пост изменён вручную, отмена заблокирована")
                return
            if announcement.edited_text and operation.after_text != announcement.edited_text:
                await self._set_job_error(job_id, "Пост изменён после правки бота, отмена заблокирована")
                return

            text = operation.before_text or ""
            entities = announcements.load_entities(operation.before_entities)
            message_entities = [MessageEntity(**entity) for entity in entities] or None
            bot = self.bot

            try:
                if announcement.media_kind:
                    await bot.edit_message_caption(
                        chat_id=announcement.chat_id,
                        message_id=announcement.message_id,
                        caption=text,
                        caption_entities=message_entities,
                    )
                else:
                    await bot.edit_message_text(
                        chat_id=announcement.chat_id,
                        message_id=announcement.message_id,
                        text=text,
                        entities=message_entities,
                        link_preview_options=LinkPreviewOptions(is_disabled=True),
                    )
            except TelegramBadRequest as exc:
                if "not modified" not in str(exc).casefold():
                    await self._set_job_error(job_id, f"Telegram: {exc}")
                    return

            now = datetime.utcnow()
            operation.status = "undone"
            await session.execute(
                update(TelegramAnnouncement)
                .where(TelegramAnnouncement.id == announcement.id)
                .values(
                    status="observed",
                    edited_text=None,
                    manually_edited=False,
                    text_snapshot=text if not announcement.media_kind else announcement.text_snapshot,
                    caption_snapshot=text if announcement.media_kind else announcement.caption_snapshot,
                    text_entities_snapshot=(
                        operation.before_entities if not announcement.media_kind else announcement.text_entities_snapshot
                    ),
                    caption_entities_snapshot=(
                        operation.before_entities if announcement.media_kind else announcement.caption_entities_snapshot
                    ),
                    updated_at=now,
                )
            )
            await session.execute(
                update(TelegramAnnouncementVod)
                .where(TelegramAnnouncementVod.id == job_id)
                .values(status="undone", undone_at=now, last_error=None, updated_at=now)
            )
            await session.commit()

    async def _restore_original(self, job_id: int) -> None:
        if self.bot is None:
            await self._set_job_error(job_id, "Telegram service is not started")
            return

        async with AsyncSessionLocal() as session:
            job = await vod_jobs.get_by_id(session, job_id)
            if job is None or job.announcement_id is None:
                return

            announcement = await announcements.get_by_id(session, job.announcement_id)
            if announcement is None:
                await self._set_job_error(job_id, "Announcement not found")
                return
            if announcement.manually_edited or announcement.status == "skipped":
                await self._set_job_error(
                    job_id,
                    "Пост изменён вручную, восстановление заблокировано",
                )
                return

            text, entities = announcements.original_of(announcement)
            if text is None and not entities:
                await self._set_job_error(job_id, "Оригинал поста не сохранён")
                return
            text = text or ""
            message_entities = [MessageEntity(**entity) for entity in entities] or None
            bot = self.bot

            try:
                if announcement.media_kind:
                    await bot.edit_message_caption(
                        chat_id=announcement.chat_id,
                        message_id=announcement.message_id,
                        caption=text,
                        caption_entities=message_entities,
                    )
                else:
                    await bot.edit_message_text(
                        chat_id=announcement.chat_id,
                        message_id=announcement.message_id,
                        text=text,
                        entities=message_entities,
                        link_preview_options=LinkPreviewOptions(is_disabled=True),
                    )
            except TelegramBadRequest as exc:
                if "not modified" not in str(exc).casefold():
                    await self._set_job_error(job_id, f"Telegram: {exc}")
                    return

            now = datetime.utcnow()
            await session.execute(
                update(TelegramPostEditOperation)
                .where(
                    TelegramPostEditOperation.job_id == job_id,
                    TelegramPostEditOperation.status == "applied",
                )
                .values(status="undone")
            )
            await session.execute(
                update(TelegramAnnouncement)
                .where(TelegramAnnouncement.id == announcement.id)
                .values(
                    status="observed",
                    edited_text=None,
                    manually_edited=False,
                    text_snapshot=text if not announcement.media_kind else announcement.text_snapshot,
                    caption_snapshot=text if announcement.media_kind else announcement.caption_snapshot,
                    text_entities_snapshot=(
                        announcement.original_entities
                        if not announcement.media_kind
                        else announcement.text_entities_snapshot
                    ),
                    caption_entities_snapshot=(
                        announcement.original_entities
                        if announcement.media_kind
                        else announcement.caption_entities_snapshot
                    ),
                    updated_at=now,
                )
            )
            await session.execute(
                update(TelegramAnnouncementVod)
                .where(TelegramAnnouncementVod.id == job_id)
                .values(
                    status="undone",
                    undone_at=now,
                    applied_text=None,
                    applied_entities=None,
                    last_error=None,
                    updated_at=now,
                )
            )
            await session.commit()
            logger.info("Announcement %s restored to original", announcement.id)

    async def _set_job_error(self, job_id: int, error: str) -> None:
        async with AsyncSessionLocal() as session:
            await session.execute(
                update(TelegramAnnouncementVod)
                .where(TelegramAnnouncementVod.id == job_id)
                .values(last_error=error, updated_at=datetime.utcnow())
            )
            await session.commit()

    # ------------------------------------------------------------------
    # Реакция на окончание трансляции
    # ------------------------------------------------------------------

    async def on_stream_ended(self, stream_session: dict[str, Any]) -> None:
        """`stream.offline`: ищем анонс и ставим задачу на VOD.

        Принимает runtime-сессию целиком, потому что нужны `stream_id` и
        границы трансляции. Ошибки не пробрасываются: вызывается из
        финализации runtime-сессии, и падение здесь сорвало бы запись
        статистики стрима.
        """
        if not self.enabled:
            return

        # В колонке stream_id текст: формат Twitch исторически строковый,
        # и int-гипотеза рано или поздно ломается на больших значениях.
        raw_stream_id = stream_session.get("stream_id")
        stream_id = str(raw_stream_id) if raw_stream_id is not None else ""
        started_at = normalize_dt(stream_session.get("started_at"))
        ended_at = normalize_dt(stream_session.get("ended_at"))
        if not stream_id or started_at is None:
            logger.debug("Stream session without stream_id/started_at, nothing to announce")
            return

        try:
            async with AsyncSessionLocal() as session:
                announcement_id = await self._bind_announcement(
                    session,
                    stream_id=stream_id,
                    started_at=started_at,
                    ended_at=ended_at,
                )
                settings_row = await post_edit_store.get_settings(session)
                delay_seconds = settings_row.delay_seconds
                job_id = await vod_jobs.create_job(
                    session,
                    announcement_id=announcement_id,
                    stream_id=stream_id,
                    stream_started_at=started_at,
                    stream_ended_at=ended_at or started_at,
                    check_delay_seconds=delay_seconds,
                )
                await session.commit()

            if job_id is None:
                logger.info(
                    "VOD job for stream %s already exists, keeping the existing one",
                    stream_id,
                )
                return

            if announcement_id is None:
                logger.info(
                    "No Telegram announcement found for stream %s; waiting for admin selection",
                    stream_id,
                )
                return

            logger.info(
                "Announcement %s bound to stream %s, VOD check in %ss",
                announcement_id,
                stream_id,
                delay_seconds,
            )
        except Exception:
            logger.exception("Failed to schedule Telegram VOD check for stream %s", stream_id)

    async def _bind_announcement(
        self,
        session,
        *,
        stream_id: str,
        started_at: datetime,
        ended_at: datetime | None,
    ) -> int | None:
        """Выбирает пост-анонс: сначала свежий кандидат, иначе переиспользование.

        Возвращает id анонса либо None.
        """
        window_start = started_at - timedelta(hours=self.before_hours)
        window_end = (ended_at or started_at) + timedelta(minutes=self.after_minutes)

        posts = await announcements.recent_posts(
            session,
            chat_id=self.chat_id,
            posted_after=window_start,
            posted_before=window_end,
        )
        bound_ids = await announcements.recent_bound_ids(
            session,
            chat_id=self.chat_id,
            posted_after=window_start,
        )

        candidates = [
            {
                "id": post.id,
                "message_id": post.message_id,
                "posted_at": post.posted_at,
                "text_snapshot": post.text_snapshot,
                "caption_snapshot": post.caption_snapshot,
                "is_forward": post.is_forward,
                # Ссылка на канал может быть скрытой подписью, и в тексте
                # поста её нет: без разобранных адресов отбор отсёк бы анонс.
                "link_urls": announcements.load_link_urls(post.link_urls),
            }
            for post in posts
            # Уже привязанные посты исключаем, но помеченные стримером как
            # skipped — тоже: их править нельзя по требованию.
            if post.status != "skipped"
        ]

        chosen = pick_candidate(
            candidates,
            matcher=self.matcher,
            started_at=started_at,
            ended_at=ended_at,
            before_hours=self.before_hours,
            after_minutes=self.after_minutes,
            exclude_message_ids=bound_ids,
        )
        if chosen:
            return chosen["id"]

        return await self._find_rebind_candidate(
            session,
            stream_id=stream_id,
            started_at=started_at,
        )

    async def _find_rebind_candidate(
        self,
        session,
        *,
        stream_id: str,
        started_at: datetime,
    ) -> int | None:
        """Тот же пост для нового broadcast после краша трансляции.

        Стример не публикует новый анонс, поэтому VOD новой трансляции
        дописывается в пост, где уже стоит ссылка на предыдущую — если
        предыдущая закончилась недавно.
        """
        rebind_since = started_at - timedelta(minutes=self.rebind_window_minutes)

        finished = await vod_jobs.recent_finished_streams(session, since=rebind_since)
        for announcement_id, previous_ended_at in finished:
            if not in_rebind_window(previous_ended_at, started_at, self.rebind_window_minutes):
                continue

            existing_jobs = await vod_jobs.jobs_for_announcement(session, announcement_id)
            if any(str(job.stream_id) == str(stream_id) for job in existing_jobs):
                continue

            logger.info(
                "Reusing announcement %s for stream %s after stream restart",
                announcement_id,
                stream_id,
            )
            return announcement_id

        return None

    # ------------------------------------------------------------------
    # Обработка очереди VOD
    # ------------------------------------------------------------------

    async def process_due_jobs(self) -> None:
        """Один проход по очереди. Дёргается поллером и ручным скриптом."""
        if not self.enabled:
            return

        try:
            async with AsyncSessionLocal() as session:
                claimed = await vod_jobs.claim_due(session)
                # Только id: сессия с FOR UPDATE держит строки задач до конца,
                # а сетевой запрос внутри цикла длится секунды и блокировал бы
                # их всё это время.
                job_ids = [job.id for job in claimed]

            for job_id in job_ids:
                await self._process_job(job_id)
        except Exception:
            logger.exception("Telegram VOD job processing failed")

    async def _process_job(self, job_id: int) -> None:
        """Одна задача в своей сессии: поиск VOD, затем правка анонса."""
        async with AsyncSessionLocal() as session:
            job = await vod_jobs.get_by_id(session, job_id)
            if job is None or job.status != "waiting":
                return
            await self._process_job_in_session(session, job)

    async def _process_job_in_session(self, session, job) -> None:
        """Одна задача: поиск VOD, затем правка анонса."""
        attempts = (job.attempts or 0) + 1

        settings_row = await post_edit_store.get_settings(session)
        if not settings_row.enabled:
            logger.info("Post-stream editing is disabled, leaving job %s waiting", job.id)
            return

        if self._http is None or self.bot is None:
            logger.warning("Telegram service is not started, skipping job %s", job.id)
            return

        try:
            vod = await fetch_vod_for_stream(
                session=self._http,
                channel_login=self.channel_login,
                stream_id=job.stream_id,
                client_id=settings.CLIENT_ID,
            )
        except VodLookupError as exc:
            exhausted = await vod_jobs.mark_failed(
                session,
                job_id=job.id,
                error=str(exc),
                attempts=attempts,
                max_attempts=self.max_attempts,
            )
            logger.warning(
                "VOD check for stream %s failed (attempt %s/%s)%s: %s",
                job.stream_id,
                attempts,
                self.max_attempts,
                " and gave up" if exhausted else "",
                exc,
            )
            return
        except Exception as unexpected:
            exhausted = await vod_jobs.mark_failed(
                session,
                job_id=job.id,
                error=f"{type(unexpected).__name__}: {unexpected}",
                attempts=attempts,
                max_attempts=self.max_attempts,
            )
            logger.exception(
                "Unexpected error checking VOD for stream %s (attempt %s/%s)",
                job.stream_id,
                attempts,
                self.max_attempts,
            )
            if exhausted:
                logger.warning("Giving up on stream %s", job.stream_id)
            return

        if vod is None or not vod.get("url"):
            await vod_jobs.mark_no_vod(
                session,
                job_id=job.id,
                reason="VOD not found in channel archive",
                attempts=attempts,
            )
            logger.warning(
                "No VOD for stream %s after %s attempts, announcement left untouched",
                job.stream_id,
                attempts,
            )
            return

        await vod_jobs.mark_resolved(
            session,
            job_id=job.id,
            vod_url=vod["url"],
            duration_minutes=vod.get("duration_minutes"),
            recorded_at=normalize_dt(vod.get("published_at") or vod.get("created_at")),
        )

        urls = await vod_jobs.resolved_urls(session, job.announcement_id)
        await self._apply_edit(session, job=job, vod_urls=urls)

    async def _apply_edit(self, session, *, job, vod_urls: list[str]) -> None:
        """Пересобирает текст подписи и правит пост."""
        announcement_id = job.announcement_id
        announcement = await announcements.get_by_id(session, announcement_id)
        if announcement is None:
            await self._set_job_error(job.id, "Announcement not found")
            return

        if announcement.status == "skipped" or announcement.manually_edited:
            await self._set_job_error(job.id, "Пост изменён вручную")
            return

        settings_row = await post_edit_store.get_settings(session)
        template = post_edit_store.template_from_settings(settings_row)
        try:
            text, entities = post_edit.render_post(
                template,
                vod_urls,
                media_kind=announcement.media_kind,
            )
        except ValueError as exc:
            await self._set_job_error(job.id, f"Некорректный шаблон: {exc}")
            return

        if not text:
            await self._set_job_error(job.id, "Шаблон дал пустой текст")
            return

        before_text, before_entities = announcements.snapshot_of(announcement)
        after_entities = announcements.dump_entities(entities)
        now = datetime.utcnow()

        operation = TelegramPostEditOperation(
            job_id=job.id,
            announcement_id=announcement_id,
            kind="publish",
            status="queued",
            before_text=before_text,
            before_entities=announcements.dump_entities(before_entities),
            after_text=text,
            after_entities=after_entities,
            created_at=now,
        )
        session.add(operation)
        await session.execute(
            update(TelegramAnnouncementVod)
            .where(TelegramAnnouncementVod.id == job.id)
            .values(status="applying", last_error=None, updated_at=now)
        )
        await session.commit()

        bot = self.bot
        if bot is None:
            await self._finish_operation(
                operation.id, job.id, success=False, error="Telegram bot is not started"
            )
            return

        message_entities = [MessageEntity(**entity) for entity in entities] or None
        try:
            if announcement.media_kind:
                await bot.edit_message_caption(
                    chat_id=announcement.chat_id,
                    message_id=announcement.message_id,
                    caption=text,
                    caption_entities=message_entities,
                )
            else:
                await bot.edit_message_text(
                    chat_id=announcement.chat_id,
                    message_id=announcement.message_id,
                    text=text,
                    entities=message_entities,
                    link_preview_options=LinkPreviewOptions(is_disabled=True),
                )
        except TelegramBadRequest as exc:
            if "not modified" not in str(exc).casefold():
                logger.error(
                    "Telegram rejected edit of announcement %s: %s",
                    announcement_id,
                    exc,
                )
                await self._finish_operation(
                    operation.id, job.id, success=False, error=f"Telegram: {exc}"
                )
                return

        await announcements.mark_edited(
            session,
            announcement_id=announcement_id,
            text=text,
        )
        await session.commit()
        await self._finish_operation(
            operation.id,
            job.id,
            success=True,
            applied_text=text,
            applied_entities=after_entities,
        )
        logger.info(
            "Announcement %s updated with %s VOD link(s): %s",
            announcement_id,
            len(vod_urls),
            text,
        )

    async def _finish_operation(
        self,
        operation_id: int,
        job_id: int,
        *,
        success: bool,
        error: str | None = None,
        applied_text: str | None = None,
        applied_entities: str | None = None,
    ) -> None:
        async with AsyncSessionLocal() as session:
            now = datetime.utcnow()
            operation = await session.get(TelegramPostEditOperation, operation_id)
            if operation is not None:
                operation.status = "applied" if success else "failed"
                operation.error = error
                operation.applied_at = now if success else None
            values = {
                "status": "edited" if success else "edit_failed",
                "last_error": error,
                "updated_at": now,
            }
            if success:
                values.update(
                    applied_at=now,
                    applied_text=applied_text,
                    applied_entities=applied_entities,
                    undone_at=None,
                )
            await session.execute(
                update(TelegramAnnouncementVod)
                .where(TelegramAnnouncementVod.id == job_id)
                .values(**values)
            )
            await session.commit()

    # ------------------------------------------------------------------
    # Служебное
    # ------------------------------------------------------------------

    @property
    def chat_id(self) -> int:
        """Числовой id чата для фильтра по БД.

        Bot API принимает и `@username`, но для колонки chat_id нужен именно
        числовой id: с @username запрос вернёт пусто и кандидат не найдётся.
        """
        raw = str(self.channel_id)
        try:
            return int(raw)
        except ValueError:
            raise ValueError(
                "TELEGRAM_CHANNEL_ID должен быть числовым id вида -100... "
                f"(сейчас {raw!r}). Узнать: python utils/telegram_channel_info.py"
            )


__all__ = ["TelegramService"]
