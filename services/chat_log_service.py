"""Запись сообщений чата и вызовов команд в PostgreSQL.

Сообщения логируются только для основного канала (`TWITCH_PRIMARY_CHANNEL`,
Tabula): остальные каналы из `TWITCH_CHANNELS` нужны для проверок команд и в
статистику не попадают. Успешные вызовы команд пишутся для всех каналов (так
было и раньше), но `stream_id` привязывается только к основному: у остальных
каналов нет runtime-сессий.

Сообщения не пишутся синхронно в обработчике EventSub: они складываются в
очередь и сбрасываются батчем (`CHAT_LOG_BATCH_SIZE` / `CHAT_LOG_FLUSH_SECONDS`).
Так ответ на команду не ждёт лишний INSERT, а поток чата не создаёт по
транзакции на сообщение.

Дедуп — по `twitch_message_id` (`ON CONFLICT DO NOTHING`): EventSub может
доставить одно сообщение повторно. Участники стрима
(`stream_chat_participants`) обновляются только по фактически вставленным
строкам, поэтому повторная доставка не раздувает счётчик.

Хранение — бессрочное (`CHAT_LOG_RETENTION_DAYS=0`). `deleted_at` остаётся для
точечного удаления по запросу. При `CHAT_LOG_RETENTION_DAYS>0` раз в сутки
чистятся старые строки.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import config.settings as settings
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from database.db import AsyncSessionLocal
from database.models import ChatMessage, StreamChatParticipant, StreamRuntimeSession
from services.command_usage_service import log_command_usage
from services.user_service import get_or_create_users_bulk
from utils.logger import get_logger

logger = get_logger("chat.log")

MAX_QUEUE_SIZE = 10000


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _to_naive_utc(value) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value
    return _utcnow()


def is_primary_channel(login: str | None) -> bool:
    if not login:
        return False
    primary = (settings.TWITCH_PRIMARY_CHANNEL or "").strip()
    return bool(primary) and login.strip().casefold() == primary.casefold()


@dataclass(slots=True)
class ChatEvent:
    kind: str  # message | command
    login: str
    display_name: str | None
    twitch_user_id: str | None
    created_at: datetime
    message: str | None = None
    twitch_message_id: str | None = None
    # Канал сообщения/команды; для сообщений всегда основной.
    channel_login: str | None = None
    is_command: bool = False
    reply_parent_message_id: str | None = None
    command_name: str | None = None
    invoked_name: str | None = None
    extra: dict = field(default_factory=dict)


def _reply_parent_id(payload) -> str | None:
    reply = getattr(payload, "reply", None)
    if reply is None:
        return None
    return getattr(reply, "parent_message_id", None)


def message_payload_channel(payload):
    """Канал сообщения EventSub.

    В TwitchIO 3 у `ChatMessage` канал называется `broadcaster`; `channel`
    остался только у `CommandContext`. Раньше здесь читался `channel`, из-за
    чего каждое сообщение отбрасывалось и `chat_messages` оставался пустым.
    `channel` оставлен как fallback для старых моков/версий TwitchIO.
    """
    channel = getattr(payload, "broadcaster", None)
    if channel is None:
        channel = getattr(payload, "channel", None)
    return channel


def build_message_event(payload, *, is_command: bool) -> ChatEvent | None:
    chatter = getattr(payload, "chatter", None)
    channel = message_payload_channel(payload)
    if chatter is None or channel is None:
        return None
    login = getattr(chatter, "name", None)
    if not login:
        return None
    return ChatEvent(
        kind="message",
        login=login,
        display_name=getattr(chatter, "display_name", None) or login,
        twitch_user_id=str(chatter.id) if getattr(chatter, "id", None) else None,
        created_at=_to_naive_utc(getattr(payload, "timestamp", None)),
        message=getattr(payload, "text", None),
        twitch_message_id=getattr(payload, "id", None),
        channel_login=getattr(channel, "name", None),
        is_command=is_command,
        reply_parent_message_id=_reply_parent_id(payload),
    )


def build_command_event(context) -> ChatEvent | None:
    author = getattr(context, "author", None)
    channel = getattr(context, "channel", None)
    if author is None or channel is None:
        return None
    login = getattr(author, "name", None)
    if not login:
        return None

    message = getattr(context, "message", None)
    invoked_with = getattr(context, "invoked_with", None)
    if not invoked_with and message is not None:
        text = (getattr(message, "text", "") or "").strip()
        invoked_with = text.split()[0] if text else None

    command = getattr(context, "command", None)
    command_name = getattr(command, "name", None)

    return ChatEvent(
        kind="command",
        login=login,
        display_name=getattr(author, "display_name", None) or login,
        twitch_user_id=str(author.id) if getattr(author, "id", None) else None,
        created_at=_to_naive_utc(
            getattr(message, "timestamp", None) if message is not None else None
        ),
        twitch_message_id=getattr(message, "id", None) if message is not None else None,
        channel_login=getattr(channel, "name", None),
        command_name=command_name,
        invoked_name=invoked_with,
    )


async def resolve_stream_id(session: AsyncSession, at: datetime) -> int | None:
    """`streams.id` для сообщения: активный стрим или недавно завершённый."""
    result = await session.execute(
        select(StreamRuntimeSession)
        .where(StreamRuntimeSession.status == "collecting")
        .order_by(StreamRuntimeSession.started_at.desc())
        .limit(1)
    )
    session_row = result.scalars().first()
    if session_row is not None:
        return int(session_row.stream_id)

    result = await session.execute(
        select(StreamRuntimeSession)
        .where(
            StreamRuntimeSession.ended_at.is_not(None),
            StreamRuntimeSession.ended_at >= at - timedelta(hours=1),
        )
        .order_by(StreamRuntimeSession.ended_at.desc())
        .limit(1)
    )
    session_row = result.scalars().first()
    return int(session_row.stream_id) if session_row is not None else None


async def insert_messages(
    session: AsyncSession,
    events: list[ChatEvent],
    *,
    streamer_id: int,
    stream_id: int | None,
) -> int:
    """Вставить сообщения и обновить присутствие. Возвращает число вставок."""
    unique: dict[str, ChatEvent] = {}
    for event in events:
        if not event.twitch_message_id or not event.message:
            continue
        unique.setdefault(event.twitch_message_id, event)

    if not unique:
        return 0

    identities = [
        (event.twitch_user_id, event.login, event.display_name)
        for event in unique.values()
    ]
    user_by_login = await get_or_create_users_bulk(session, identities)

    rows = []
    for event in unique.values():
        user = user_by_login.get(event.twitch_user_id or event.login)
        if user is None:
            continue
        rows.append(
            {
                "user_id": int(user.id),
                "streamer_id": int(streamer_id),
                "message": event.message,
                "twitch_message_id": event.twitch_message_id,
                "stream_id": stream_id,
                "channel_login": settings.TWITCH_PRIMARY_CHANNEL,
                "is_command": bool(event.is_command),
                "reply_parent_message_id": event.reply_parent_message_id,
                "created_at": event.created_at,
            }
        )

    if not rows:
        return 0

    result = await session.execute(
        pg_insert(ChatMessage)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["twitch_message_id"])
        .returning(ChatMessage.twitch_message_id, ChatMessage.user_id, ChatMessage.created_at)
    )
    inserted = result.all()

    if stream_id is not None and inserted:
        await _upsert_participants(session, inserted, stream_id=stream_id)

    return len(inserted)


async def _upsert_participants(
    session: AsyncSession,
    inserted: list,
    *,
    stream_id: int,
) -> None:
    aggregates: dict[int, dict] = {}
    for _message_id, user_id, created_at in inserted:
        key = int(user_id)
        bucket = aggregates.get(key)
        if bucket is None:
            aggregates[key] = {
                "stream_id": int(stream_id),
                "user_id": key,
                "first_message_at": created_at,
                "last_message_at": created_at,
                "messages_count": 1,
            }
        else:
            if created_at < bucket["first_message_at"]:
                bucket["first_message_at"] = created_at
            if created_at > bucket["last_message_at"]:
                bucket["last_message_at"] = created_at
            bucket["messages_count"] += 1

    if not aggregates:
        return

    stmt = pg_insert(StreamChatParticipant).values(list(aggregates.values()))
    stmt = stmt.on_conflict_do_update(
        constraint="uq_stream_chat_participants_stream_user",
        set_={
            "first_message_at": func.least(
                StreamChatParticipant.first_message_at,
                stmt.excluded.first_message_at,
            ),
            "last_message_at": func.greatest(
                StreamChatParticipant.last_message_at,
                stmt.excluded.last_message_at,
            ),
            "messages_count": StreamChatParticipant.messages_count
            + stmt.excluded.messages_count,
        },
    )
    await session.execute(stmt)


def _login_key(login: str | None) -> str:
    return (login or "").strip().casefold()


async def flush_events(events: list[ChatEvent]) -> None:
    if not events:
        return

    async with AsyncSessionLocal() as session:
        at = max(event.created_at for event in events)
        stream_id = await resolve_stream_id(session, at)

        message_events = [event for event in events if event.kind == "message"]
        command_events = [event for event in events if event.kind == "command"]

        # Стримеры всех каналов, где были успешные команды. Ключ словаря —
        # casefold-логин: Twitch отдаёт его в нижнем регистре, а в настройках
        # канал может быть записан иначе.
        streamer_logins: dict[str, str] = {}
        primary_login = (settings.TWITCH_PRIMARY_CHANNEL or "").strip()
        if primary_login:
            streamer_logins[_login_key(primary_login)] = primary_login
        for event in command_events:
            login = (event.channel_login or primary_login or "").strip()
            if login:
                streamer_logins.setdefault(_login_key(login), login)

        streamers = await get_or_create_users_bulk(
            session,
            [(None, login, login) for login in streamer_logins.values()],
        )
        streamers_by_login = {
            _login_key(key): user for key, user in streamers.items()
        }

        primary_streamer = streamers_by_login.get(_login_key(primary_login))
        if message_events and primary_streamer is None:
            logger.warning("Cannot resolve streamer user for chat log")
        elif message_events:
            await insert_messages(
                session,
                message_events,
                streamer_id=int(primary_streamer.id),
                stream_id=stream_id,
            )

        if command_events:
            identities = [
                (event.twitch_user_id, event.login, event.display_name)
                for event in command_events
            ]
            users_by_login = await get_or_create_users_bulk(session, identities)
            for event in command_events:
                user = users_by_login.get(event.twitch_user_id or event.login)
                channel_login = (event.channel_login or primary_login or "").strip()
                streamer_user = streamers_by_login.get(_login_key(channel_login))
                if user is None or streamer_user is None or not event.command_name:
                    continue
                # У неосновных каналов нет runtime-сессий: stream_id = NULL.
                event_stream_id = (
                    stream_id if is_primary_channel(channel_login) else None
                )
                await log_command_usage(
                    session,
                    user,
                    streamer_user,
                    event.command_name,
                    stream_id=event_stream_id,
                    invoked_name=event.invoked_name,
                    twitch_message_id=event.twitch_message_id,
                    created_at=event.created_at,
                )

        await session.commit()


async def cleanup_old_messages(
    session: AsyncSession, *, retention_days: int
) -> int:
    if retention_days <= 0:
        return 0
    cutoff = _utcnow() - timedelta(days=retention_days)
    result = await session.execute(
        delete(ChatMessage).where(ChatMessage.created_at < cutoff)
    )
    return int(result.rowcount or 0)


class ChatLogService:
    """Очередь и фоновый воркер записи чата."""

    def __init__(self):
        self._queue: asyncio.Queue[ChatEvent] = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)
        self._task: asyncio.Task | None = None
        self._stopping = False
        self._last_cleanup_date = None
        self._dropped = 0

    @property
    def enabled(self) -> bool:
        return bool(settings.CHAT_LOG_ENABLED)

    async def start(self) -> None:
        if not self.enabled:
            logger.info("Chat log disabled by settings")
            return
        if self._task and not self._task.done():
            return
        self._task = asyncio.get_running_loop().create_task(
            self._run(), name="chat-log-worker"
        )
        logger.info(
            "Chat log worker started (batch=%s, flush=%ss)",
            settings.CHAT_LOG_BATCH_SIZE,
            settings.CHAT_LOG_FLUSH_SECONDS,
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

    def enqueue_message(self, payload, *, is_command: bool) -> None:
        if not self.enabled:
            return
        channel = message_payload_channel(payload)
        if channel is not None and not is_primary_channel(getattr(channel, "name", None)):
            return
        event = build_message_event(payload, is_command=is_command)
        if event is not None:
            self._put(event)

    def enqueue_command(self, context) -> None:
        # Успешные команды логируются и для неосновных каналов (история
        # использования команд не привязана к статистике основного канала).
        if not self.enabled:
            return
        event = build_command_event(context)
        if event is not None:
            self._put(event)

    def _put(self, event: ChatEvent) -> None:
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self._dropped += 1
            if self._dropped in (1, 100, 1000):
                logger.warning(
                    "Chat log queue is full, dropped %s message(s)", self._dropped
                )

    async def _run(self) -> None:
        flush_seconds = max(float(settings.CHAT_LOG_FLUSH_SECONDS), 0.1)
        max_batch = max(int(settings.CHAT_LOG_BATCH_SIZE), 1)
        loop = asyncio.get_running_loop()

        while not self._stopping:
            try:
                batch = [await self._queue.get()]
            except asyncio.CancelledError:
                raise

            # Сразу забираем то, что уже накопилось.
            while len(batch) < max_batch:
                try:
                    batch.append(self._queue.get_nowait())
                except asyncio.QueueEmpty:
                    break

            # Неполный батч добираем в пределах окна flush_seconds: сообщение
            # появляется в БД не позже чем через CHAT_LOG_FLUSH_SECONDS.
            if len(batch) < max_batch:
                deadline = loop.time() + flush_seconds
                while len(batch) < max_batch:
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        break
                    try:
                        batch.append(
                            await asyncio.wait_for(
                                self._queue.get(), timeout=remaining
                            )
                        )
                    except asyncio.TimeoutError:
                        break

            await self._flush(batch)

        # При остановке дописываем то, что успело попасть в очередь.
        remaining_batch: list[ChatEvent] = []
        while True:
            try:
                remaining_batch.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if remaining_batch:
            await self._flush(remaining_batch)

    async def _flush(self, batch: list[ChatEvent]) -> None:
        try:
            await flush_events(batch)
        except Exception:
            logger.exception("Failed to flush %s chat event(s)", len(batch))

        await self._maybe_cleanup()

    async def _maybe_cleanup(self) -> None:
        retention = int(settings.CHAT_LOG_RETENTION_DAYS or 0)
        if retention <= 0:
            return
        today = _utcnow().date()
        if self._last_cleanup_date == today:
            return
        self._last_cleanup_date = today
        try:
            async with AsyncSessionLocal() as session:
                deleted = await cleanup_old_messages(session, retention_days=retention)
                await session.commit()
            if deleted:
                logger.info("Chat log cleanup removed %s message(s)", deleted)
        except Exception:
            logger.exception("Chat log cleanup failed")
