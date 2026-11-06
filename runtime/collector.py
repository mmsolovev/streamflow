"""Runtime-коллектор статистики основного канала.

Источник истины — PostgreSQL (`stream_runtime_sessions`, `stream_runtime_samples`,
`stream_runtime_buckets`). В памяти остаётся только «живой» срез текущей сессии:
его достаточно для сэмплирования и событий `channel.update` / `stream.offline`.

JSON-хранилище (`runtime.storage`) больше не используется в рабочем пути:
всё, что нужно для восстановления после рестарта, восстанавливается из БД.
"""

import asyncio
import inspect
from datetime import datetime, timezone

import config.settings as settings
from database.db import AsyncSessionLocal
from runtime import repository, sampler
from runtime.utils import now_iso, parse_iso
from utils.logger import get_logger


class RuntimeStreamCollector:
    def __init__(self, bot):
        self.bot = bot
        self.logger = get_logger("runtime.collector")
        self.broadcaster_id: int | None = None
        # Снимок формы StreamSession с stream_db_id/session_id из БД.
        self.active_session: dict | None = None
        self.sample_interval_seconds = settings.STREAM_RUNTIME_SAMPLE_SECONDS
        self.sampling_task: asyncio.Task | None = None
        self.followers_sampling_enabled = True
        self.finalize_listeners: list = []

    # ------------------------------------------------------------------
    # Listeners
    # ------------------------------------------------------------------

    def add_finalize_listener(self, listener):
        """Подписывает колбэк на финализацию runtime-сессии.

        Единая точка для потребителей конца трансляции. Отдельный хук в
        EventSub не делается сознательно: stream.offline покрывает не всё
        (crash/recover проходят через recovered_* на bootstrap), а этот вызов —
        все сценарии разом.
        """
        if listener not in self.finalize_listeners:
            self.finalize_listeners.append(listener)

    async def _notify_finalize_listeners(self, session):
        for listener in self.finalize_listeners:
            try:
                result = listener(session)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                self.logger.exception(
                    "Finalize listener %s failed for session %s",
                    getattr(listener, "__name__", listener),
                    session.get("stream_id"),
                )

    # ------------------------------------------------------------------
    # Bootstrap / recovery
    # ------------------------------------------------------------------

    async def bootstrap(self, broadcaster_id: int):
        self.broadcaster_id = int(broadcaster_id)
        self.active_session = None

        live_stream = None
        try:
            live_stream = await sampler.fetch_live_stream_with_refresh(self.bot)
        except Exception as exc:
            self.logger.warning("Failed to fetch live stream on bootstrap: %s", exc)

        async with AsyncSessionLocal() as db:
            collecting = await repository.get_collecting_sessions(db)
            current = None
            if live_stream is not None:
                for session in collecting:
                    if str(session.twitch_stream_id) == str(live_stream.id):
                        current = session
                        break

            if current is not None:
                for session in collecting:
                    if session.id == current.id:
                        continue
                    await repository.finalize_session(
                        db,
                        session,
                        ended_at=session.last_sample_at or session.started_at,
                        reason="recovered_other_session_on_bootstrap",
                    )
                snapshot = await repository.build_session_snapshot(db, current)
                await db.commit()
                self.active_session = snapshot
                self.logger.info(
                    "Recovered active session %s for live stream %s",
                    current.id,
                    live_stream.id,
                )
                await self.capture_runtime_sample(
                    stream_snapshot=live_stream, reason="collector.bootstrap.recovered"
                )
                await self.ensure_sampling_started()
                return

            reason = (
                "recovered_new_live_stream_on_bootstrap"
                if live_stream is not None
                else "recovered_offline_on_bootstrap"
            )
            for session in collecting:
                self.logger.info(
                    "Finalizing collecting session %s before bootstrap continues", session.id
                )
                await repository.finalize_session(
                    db,
                    session,
                    ended_at=session.last_sample_at or session.started_at,
                    reason=reason,
                )
            await db.commit()

        if live_stream is not None:
            self.logger.info(
                "Creating active session from current live stream %s", live_stream.id
            )
            await self._start_session_from_stream(live_stream, source="bootstrap")
            await self.capture_runtime_sample(stream_snapshot=live_stream, reason="bootstrap")
            await self.ensure_sampling_started()

    # ------------------------------------------------------------------
    # Stream lifecycle
    # ------------------------------------------------------------------

    async def handle_stream_online(self, data, stream_snapshot=None):
        stream_id = str(
            getattr(stream_snapshot, "id", None) or getattr(data, "id", None)
        )

        if self.active_session and str(self.active_session.get("stream_id")) == stream_id:
            self.logger.info("Ignoring duplicate stream.online for stream %s", stream_id)
            await self.capture_runtime_sample(
                stream_snapshot=stream_snapshot, reason="stream.online.duplicate"
            )
            await self.ensure_sampling_started(initial_stream=stream_snapshot)
            return

        if self.active_session:
            if await self._try_reconnect(stream_id):
                await self.capture_runtime_sample(
                    stream_snapshot=stream_snapshot, reason="stream.online.reconnect"
                )
                await self.ensure_sampling_started(initial_stream=stream_snapshot)
                return

            self.logger.info(
                "Finalizing previous active session %s before starting stream %s",
                self.active_session.get("stream_id"),
                stream_id,
            )
            await self.finalize_active_session(
                ended_at=self._inferred_end_iso(),
                reason="superseded_by_new_stream_online",
            )

        if stream_snapshot is not None:
            await self._start_session_from_stream(
                stream_snapshot, source="eventsub.stream_online"
            )
        else:
            started_at = getattr(data, "started_at", None) or datetime.now(timezone.utc)
            await self._start_session(
                stream_id=stream_id,
                started_at=started_at,
                title=None,
                category_name=None,
                category_id=None,
                source="eventsub.stream_online.partial",
            )

        await self.capture_runtime_sample(
            stream_snapshot=stream_snapshot, reason="stream.online"
        )
        await self.ensure_sampling_started()

    async def handle_stream_offline(self, ended_at: str | None = None):
        if not self.active_session:
            self.logger.info("Ignoring stream.offline without active session")
            return

        await self.finalize_active_session(
            ended_at=ended_at or now_iso(),
            reason="eventsub.stream_offline",
        )

    async def _try_reconnect(self, twitch_stream_id: str) -> bool:
        """Склеить новый Twitch stream_id с текущей сессией, если это реконнект."""
        if not self.active_session:
            return False

        stream_db_id = self.active_session.get("stream_db_id")
        if stream_db_id is None:
            return False

        async with AsyncSessionLocal() as db:
            session = await repository.get_session_by_stream(db, int(stream_db_id))
            if session is None:
                return False
            if not await repository.reopen_session_for_reconnect(
                db, session, twitch_stream_id=twitch_stream_id
            ):
                await db.rollback()
                return False
            snapshot = await repository.build_session_snapshot(db, session)
            await db.commit()

        self.active_session = snapshot
        return True

    async def _start_session_from_stream(self, stream, source: str):
        await self._start_session(
            stream_id=str(stream.id),
            started_at=stream.started_at,
            title=stream.title,
            category_name=stream.game_name,
            category_id=str(stream.game_id) if stream.game_id is not None else None,
            source=source,
        )

    async def _start_session(
        self,
        *,
        stream_id: str,
        started_at,
        title: str | None,
        category_name: str | None,
        category_id: str | None,
        source: str,
    ):
        started_dt = (
            parse_iso(started_at) if isinstance(started_at, str) else started_at
        )
        if started_dt is None:
            started_dt = datetime.now(timezone.utc)

        async with AsyncSessionLocal() as db:
            stream = await repository.resolve_stream(
                db,
                twitch_stream_id=str(stream_id),
                started_at=started_dt,
                title=title,
            )
            session = await repository.claim_session(
                db,
                stream=stream,
                twitch_stream_id=str(stream_id),
                started_at=started_dt,
                broadcaster_id=self.broadcaster_id,
            )
            snapshot = await repository.build_session_snapshot(db, session)
            await db.commit()

        self.active_session = snapshot
        self.logger.info(
            "Started runtime stream session %s (stream_db_id=%s, session_id=%s, source=%s)",
            stream_id,
            snapshot.get("stream_db_id"),
            snapshot.get("session_id"),
            source,
        )

    # ------------------------------------------------------------------
    # Channel update / follow
    # ------------------------------------------------------------------

    async def handle_channel_update(self, data):
        if not self.active_session:
            self.logger.info("Ignoring channel.update for collector without active session")
            return

        sampled_at = datetime.now(timezone.utc)
        category_id = str(data.category_id) if data.category_id is not None else None

        stream_db_id = self.active_session.get("stream_db_id")
        if stream_db_id is None:
            return

        async with AsyncSessionLocal() as db:
            session = await repository.get_session_by_stream(db, int(stream_db_id))
            if session is None or session.status != "collecting":
                return
            viewers, followers = await repository.get_latest_sample_values(
                db, int(stream_db_id)
            )
            await repository.insert_sample(
                db,
                session=session,
                sampled_at=sampled_at,
                viewers=viewers,
                followers=followers,
                title=data.title,
                category_name=data.category_name,
                category_id=category_id,
                source="eventsub.channel_update",
            )
            await db.commit()

        self._apply_channel_update(
            title=data.title,
            category_name=data.category_name,
            category_id=category_id,
            changed_at=sampled_at,
        )

    def handle_follow(self, data):
        """Follow-события не персистятся: прирост считается по сэмплам фолловеров.

        Метод оставлен точкой расширения и для диагностических логов.
        """
        if not self.active_session:
            self.logger.info("Ignoring channel.follow.v2 without active session")
            return
        self.logger.info(
            "Follow event for user %s at %s (not persisted, follower samples are source of truth)",
            getattr(getattr(data, "user", None), "id", "?"),
            getattr(data, "followed_at", "?"),
        )

    def _apply_channel_update(
        self,
        *,
        title: str | None,
        category_name: str | None,
        category_id: str | None,
        changed_at: datetime,
    ) -> None:
        if not self.active_session:
            return

        session = self.active_session
        session["collector"]["updated_at"] = now_iso()

        if title:
            if not session.get("title"):
                session["title"] = title
                session["title_start"] = title
            if session.get("title_current") != title:
                session["title_current"] = title
                session["title_history"].append(
                    {
                        "title": title,
                        "changed_at": _iso(changed_at),
                        "source": "eventsub.channel_update",
                    }
                )

        if not category_name:
            return

        if session.get("category_name") == category_name:
            return

        session["category_name"] = category_name
        session["category_id"] = category_id
        session["category_history"].append(
            {
                "category_id": category_id,
                "category_name": category_name,
                "changed_at": _iso(changed_at),
                "source": "eventsub.channel_update",
            }
        )
        segments = session.setdefault("game_segments", [])
        if segments and segments[-1].get("ended_at") is None:
            segments[-1]["ended_at"] = _iso(changed_at)
        segments.append(
            {
                "category_id": category_id,
                "category_name": category_name,
                "started_at": _iso(changed_at),
                "ended_at": None,
                "source": "eventsub.channel_update",
            }
        )

    # ------------------------------------------------------------------
    # Sampling
    # ------------------------------------------------------------------

    async def ensure_sampling_started(self, initial_stream=None):
        if not self.active_session:
            return

        if initial_stream is not None:
            await self.capture_runtime_sample(
                stream_snapshot=initial_stream, reason="sampling.initial"
            )

        if self.sampling_task and not self.sampling_task.done():
            return

        self.sampling_task = asyncio.get_running_loop().create_task(self._sampling_loop())
        self.logger.info(
            "Started runtime sampling loop with interval %ss",
            self.sample_interval_seconds,
        )

    async def _sampling_loop(self):
        try:
            while self.active_session:
                await asyncio.sleep(self.sample_interval_seconds)
                await self.capture_runtime_sample(reason="sampling.loop")
        except asyncio.CancelledError:
            raise
        except Exception:
            self.logger.exception("Runtime sampling loop failed")

    async def capture_runtime_sample(
        self,
        stream_snapshot=None,
        reason: str = "sample",
        allow_offline_followers: bool = False,
    ):
        if not self.active_session:
            return

        active_stream_id = str(self.active_session.get("stream_id"))
        sampled_at = datetime.now(timezone.utc)

        current_stream = stream_snapshot
        if current_stream is None:
            try:
                current_stream = await sampler.fetch_live_stream_with_refresh(self.bot)
            except Exception as exc:
                self.logger.warning(
                    "Failed to fetch live stream snapshot for %s: %s", reason, exc
                )
                current_stream = None

        viewers: int | None = None
        title = self.active_session.get("title_current")
        category_name = self.active_session.get("category_name")
        category_id = self.active_session.get("category_id")

        if current_stream is not None and str(current_stream.id) == active_stream_id:
            viewers = int(current_stream.viewer_count)
            if current_stream.title:
                title = current_stream.title
            if current_stream.game_name:
                category_name = current_stream.game_name
                category_id = (
                    str(current_stream.game_id)
                    if current_stream.game_id is not None
                    else None
                )
        elif current_stream is not None:
            self.logger.info(
                "Skipping viewer sample for mismatched live stream %s while active session is %s",
                current_stream.id,
                active_stream_id,
            )
        elif not allow_offline_followers:
            self.logger.info("Live stream snapshot unavailable for %s", reason)

        followers: int | None = None
        if self.followers_sampling_enabled and self.broadcaster_id is not None:
            followers = await sampler.fetch_followers_count(self.bot, self.broadcaster_id)
            if followers is None:
                self.followers_sampling_enabled = False
                self.logger.warning(
                    "Follower sampling disabled until restart: channels/followers unavailable"
                )

        if viewers is None and followers is None:
            return

        stream_db_id = self.active_session.get("stream_db_id")
        if stream_db_id is None:
            return

        async with AsyncSessionLocal() as db:
            session = await repository.get_session_by_stream(db, int(stream_db_id))
            if session is None or session.status != "collecting":
                return
            inserted = await repository.insert_sample(
                db,
                session=session,
                sampled_at=sampled_at,
                viewers=viewers,
                followers=followers,
                title=title,
                category_name=category_name,
                category_id=category_id,
                source=reason,
            )
            await db.commit()

        if not inserted:
            return

        if self.active_session:
            self.active_session["collector"]["updated_at"] = now_iso()
            self.active_session["last_sample_at"] = _iso(sampled_at)
            self.active_session["samples_count"] = int(
                self.active_session.get("samples_count") or 0
            ) + 1
            if title:
                self.active_session["title_current"] = title
            if category_name:
                self.active_session["category_name"] = category_name
                self.active_session["category_id"] = category_id

    # ------------------------------------------------------------------
    # Finalization
    # ------------------------------------------------------------------

    async def finalize_active_session(self, *, ended_at: str, reason: str):
        if not self.active_session:
            return None

        await self._stop_sampling()

        ended_dt = parse_iso(ended_at)
        now_dt = datetime.now(timezone.utc)
        if ended_dt is None or (now_dt - ended_dt).total_seconds() <= 30:
            await self.capture_runtime_sample(
                stream_snapshot=None,
                reason="stream.finalize",
                allow_offline_followers=True,
            )

        stream_db_id = self.active_session.get("stream_db_id")
        self.active_session = None

        if stream_db_id is None:
            return None

        final_ended = ended_dt or datetime.now(timezone.utc)
        snapshot = None
        async with AsyncSessionLocal() as db:
            session = await repository.get_session_by_stream(db, int(stream_db_id))
            if session is None:
                self.logger.warning(
                    "Runtime session for stream %s disappeared before finalization",
                    stream_db_id,
                )
                return None
            snapshot = await repository.finalize_session(
                db,
                session,
                ended_at=final_ended,
                reason=reason,
            )
            await db.commit()

        self.logger.info(
            "Finalized runtime stream session %s with reason %s",
            snapshot.get("stream_id"),
            reason,
        )

        await self._notify_finalize_listeners(snapshot)
        return snapshot

    async def _stop_sampling(self) -> None:
        if self.sampling_task and not self.sampling_task.done():
            self.sampling_task.cancel()
            try:
                await self.sampling_task
            except asyncio.CancelledError:
                pass
        self.sampling_task = None

    def _inferred_end_iso(self) -> str:
        """Последняя известная активность сессии — без «now», иначе средние ломаются."""
        if self.active_session:
            last_sample = self.active_session.get("last_sample_at")
            if last_sample:
                return last_sample
        return now_iso()


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()
