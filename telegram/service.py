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

import config.settings as settings
from database.db import AsyncSessionLocal
from telegram import announcements, vod_jobs
from telegram.handlers import router as channel_router
from telegram.matcher import (
    build_channel_link_matcher,
    in_rebind_window,
    normalize_dt,
    pick_candidate,
)
from telegram.templates import (
    build_finished_entities,
    fit_entities,
    fit_to_media_limit,
)
from telegram.vod_service import VodLookupError, fetch_vod_for_stream
from utils.logger import get_logger


logger = get_logger("telegram.service")


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

            logger.info(
                "Telegram integration started for chat %s, primary channel %s",
                self.channel_id,
                self.channel_login,
            )
        except Exception:
            logger.exception("Failed to start Telegram integration")
            await self.stop()

    async def stop(self) -> None:
        for task in (self._polling_task, self._poller_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self._polling_task = None
        self._poller_task = None

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
                if announcement_id is None:
                    logger.info(
                        "No Telegram announcement found for stream %s, nothing scheduled",
                        stream_id,
                    )
                    return

                job_id = await vod_jobs.create_job(
                    session,
                    announcement_id=announcement_id,
                    stream_id=stream_id,
                    stream_started_at=started_at,
                    stream_ended_at=ended_at or started_at,
                    check_delay_seconds=self.check_delay_seconds,
                )
                await session.commit()

            if job_id is None:
                logger.info(
                    "VOD job for stream %s already exists, keeping the existing one",
                    stream_id,
                )
                return

            logger.info(
                "Announcement %s bound to stream %s, VOD check in %ss",
                announcement_id,
                stream_id,
                self.check_delay_seconds,
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
        await self._apply_edit(session, announcement_id=job.announcement_id, vod_urls=urls)

    async def _apply_edit(self, session, *, announcement_id: int, vod_urls: list[str]) -> None:
        """Пересобирает текст подписи и правит пост.

        Текст всегда строится заново из всех найденных VOD анонса: так после
        краша трансляции в подписи оказываются обе ссылки, а повторный вызов
        с тем же набором даёт тот же результат.
        """
        announcement = await announcements.get_by_id(session, announcement_id)
        if announcement is None:
            logger.warning("Announcement %s disappeared before edit", announcement_id)
            return

        if announcement.status == "skipped" or announcement.manually_edited:
            logger.info("Announcement %s is skipped or edited manually, not touching", announcement_id)
            return

        # edited_text хранит ОТРИСОВАННЫЙ текст: именно он вернётся в
        # edited_channel_post. В API уходит тот же самый текст плюс entities,
        # поэтому сравнение с возвращённым значением будет точным.
        # build_finished_entities сам подбирает число ссылок под лимит поста;
        # fit_* ниже — страховка на случай, если шаблон перестанет влезать.
        text, entities = build_finished_entities(
            vod_urls, announcement.media_kind
        )
        text = fit_to_media_limit(text, announcement.media_kind)
        entities = fit_entities(text, entities)

        if announcement.edited_text and announcement.edited_text == text:
            logger.info("Announcement %s already contains the target text", announcement_id)
            return

        await announcements.mark_edited(
            session,
            announcement_id=announcement_id,
            text=text,
        )
        await session.commit()

        bot = self.bot
        if bot is None:
            logger.warning(
                "Telegram bot is not started, cannot edit announcement %s", announcement_id
            )
            return

        # Шаблоны собирают сущности словарями, чтобы не зависеть от aiogram и
        # оставаться тестируемыми. Здесь, на границе с API, они превращаются
        # в MessageEntity: приведёт ли aiogram словари сам — неизвестно, и
        # полагаться на это в коде, который переписывает пост стримера,
        # не стоит.
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
            # «message is not modified» — это успех, а не ошибка: пост уже
            # содержит нужный текст. Не откатываем статус.
            if "not modified" in str(exc).casefold():
                logger.info("Announcement %s already has the VOD link", announcement_id)
                return

            logger.error(
                "Telegram rejected edit of announcement %s: %s",
                announcement_id,
                exc,
            )
            await announcements.mark_skipped(
                session,
                announcement_id=announcement_id,
                reason=f"telegram_error: {exc}",
            )
            await session.commit()
            return

        logger.info(
            "Announcement %s updated with %s VOD link(s): %s",
            announcement_id,
            len(vod_urls),
            text,
        )

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
