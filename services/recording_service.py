"""Единый реестр записей стримов (`stream_recordings`).

VOD — это запись трансляции на Twitch. Один стрим может иметь несколько
записей: после краша трансляции стример выходит в новый broadcast, и у него
свой VOD. Поэтому запись идентифицируется парой (источник, video_id), а не
только `streams.id`; `twitch_stream_id` хранит broadcast id, к которому
относится запись.

Все пути записи VOD (runtime-воркер Telegram, ручная проверка в админке,
`sync_vods`, импорт TwitchTracker) идут через `upsert_recording`, чтобы не
плодить дубли и не расходиться в том, что считать актуальной записью.

Истёкшие записи не удаляются: `is_available=False` скрывает их на сайте, но
оставляет историю и связь с постом.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Stream, StreamRecording

DEFAULT_SOURCE = "twitch"

_VIDEO_ID_RE = re.compile(r"/videos/(\d+)")


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def to_naive_utc(value: datetime | str | None) -> datetime | None:
    """datetime | ISO-строка -> naive UTC. Как в остальных таблицах проекта."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            value = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def parse_video_id(url: str | None) -> str | None:
    """Twitch video id из ссылки: `.../videos/2915709311` -> `2915709311`."""
    if not url:
        return None
    match = _VIDEO_ID_RE.search(str(url))
    return match.group(1) if match else None


def parse_duration_minutes(value: Any) -> int | None:
    """`"7h29m15s"` -> минуты. Формат длительности Twitch Helix."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        seconds = int(value)
    else:
        text = str(value).strip().lower()
        match = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?", text)
        if not match:
            return None
        hours, minutes, seconds_part = (int(part or 0) for part in match.groups())
        seconds = hours * 3600 + minutes * 60 + seconds_part
    if seconds <= 0:
        return None
    # Не round(): round(62.5) == 62, длительность показывалась бы меньше.
    return int(seconds / 60 + 0.5)


def fields_from_vod(vod: dict[str, Any]) -> dict[str, Any]:
    """Поля записи из объекта Twitch Helix `/videos`."""
    url = str(vod.get("url") or "").strip() or None
    video_id = str(vod.get("id") or "").strip() or parse_video_id(url)
    broadcast_id = str(vod.get("stream_id") or "").strip() or None
    if broadcast_id == "0":
        broadcast_id = None
    return {
        "url": url,
        "twitch_video_id": video_id,
        "twitch_stream_id": broadcast_id,
        "duration_minutes": parse_duration_minutes(vod.get("duration")),
        "recorded_at": to_naive_utc(vod.get("created_at") or vod.get("published_at")),
    }


async def get_by_id(
    session: AsyncSession, recording_id: int
) -> StreamRecording | None:
    return await session.get(StreamRecording, recording_id)


async def find_recording(
    session: AsyncSession,
    *,
    url: str | None,
    twitch_video_id: str | None = None,
    source: str = DEFAULT_SOURCE,
) -> StreamRecording | None:
    """Запись по video_id, иначе по URL (legacy-строки без video_id)."""
    video_id = (twitch_video_id or parse_video_id(url) or "").strip() or None
    conditions = []
    if video_id:
        conditions.append(StreamRecording.twitch_video_id == video_id)
    if url:
        conditions.append(StreamRecording.url == url)
    if not conditions:
        return None

    result = await session.execute(
        select(StreamRecording)
        .where(
            StreamRecording.source == source,
            or_(*conditions),
        )
        .order_by(StreamRecording.id.asc())
        .limit(1)
    )
    return result.scalars().first()


async def upsert_recording(
    session: AsyncSession,
    *,
    stream_id: int,
    url: str | None,
    twitch_stream_id: str | None = None,
    twitch_video_id: str | None = None,
    duration_minutes: int | None = None,
    recorded_at: datetime | str | None = None,
    source: str = DEFAULT_SOURCE,
    is_available: bool = True,
) -> StreamRecording | None:
    """Создать или обновить запись. Возвращает строку либо None без URL.

    Идемпотентно: повторный вызов с теми же данными ничего не дублирует.
    Если запись уже была привязана к другому стриму (поиск по времени), но
    теперь известен точный broadcast id, привязка исправляется.
    """
    url = (url or "").strip() or None
    if not url:
        return None

    twitch_video_id = (twitch_video_id or parse_video_id(url) or "").strip() or None
    twitch_stream_id = (twitch_stream_id or "").strip() or None
    if twitch_stream_id == "0":
        twitch_stream_id = None
    recorded = to_naive_utc(recorded_at)
    now = utcnow()

    recording = await find_recording(
        session,
        url=url,
        twitch_video_id=twitch_video_id,
        source=source,
    )

    if recording is None:
        recording = StreamRecording(
            stream_id=int(stream_id),
            source=source,
            url=url,
            twitch_stream_id=twitch_stream_id,
            twitch_video_id=twitch_video_id,
            duration_minutes=duration_minutes,
            recorded_at=recorded,
            is_available=bool(is_available),
            created_at=now,
            updated_at=now,
        )
        session.add(recording)
        await session.flush()
        return recording

    changed = False
    if recording.url != url:
        recording.url = url
        changed = True
    if twitch_video_id and recording.twitch_video_id != twitch_video_id:
        recording.twitch_video_id = twitch_video_id
        changed = True
    if twitch_stream_id and recording.twitch_stream_id != twitch_stream_id:
        recording.twitch_stream_id = twitch_stream_id
        changed = True
    # Точная привязка важнее подобранной по времени: VOD принадлежит
    # конкретному broadcast, а не «примерно тому же вечеру».
    if twitch_stream_id and int(recording.stream_id) != int(stream_id):
        recording.stream_id = int(stream_id)
        changed = True
    if duration_minutes is not None and recording.duration_minutes != duration_minutes:
        recording.duration_minutes = duration_minutes
        changed = True
    if recorded is not None and recording.recorded_at != recorded:
        recording.recorded_at = recorded
        changed = True
    if bool(recording.is_available) != bool(is_available):
        recording.is_available = bool(is_available)
        changed = True
    if changed:
        recording.updated_at = now
    return recording


async def upsert_from_vod(
    session: AsyncSession,
    *,
    stream_id: int,
    vod: dict[str, Any],
    source: str = DEFAULT_SOURCE,
    is_available: bool = True,
) -> StreamRecording | None:
    fields = fields_from_vod(vod)
    return await upsert_recording(
        session,
        stream_id=stream_id,
        source=source,
        is_available=is_available,
        **fields,
    )


async def link_recording_to_job(
    session: AsyncSession,
    *,
    stream_db_id: int | None,
    twitch_stream_id: str | None,
) -> int | None:
    """`streams.id` по broadcast id; применяется, когда runtime-строки ещё нет."""
    if stream_db_id is not None:
        return int(stream_db_id)
    if not twitch_stream_id:
        return None
    result = await session.execute(
        select(Stream.id).where(Stream.external_id == str(twitch_stream_id))
    )
    return result.scalar_one_or_none()


async def ensure_stream(
    session: AsyncSession,
    *,
    twitch_stream_id: str,
    stream_db_id: int | None = None,
    started_at: datetime | str | None = None,
    ended_at: datetime | str | None = None,
) -> int:
    """`streams.id` для broadcast id, при необходимости создаёт строку.

    Нужно для старых VOD-задач: запись на Twitch есть, а строки `streams`
    в БД нет. Без этого ссылку некуда было бы положить после того, как
    `vod_url` перестал храниться в очереди.
    """
    resolved = await link_recording_to_job(
        session,
        stream_db_id=stream_db_id,
        twitch_stream_id=twitch_stream_id,
    )
    if resolved is not None:
        return int(resolved)

    now = utcnow()
    stream = Stream(
        external_id=str(twitch_stream_id),
        started_at=to_naive_utc(started_at),
        ended_at=to_naive_utc(ended_at),
        created_at=now,
        updated_at=now,
    )
    session.add(stream)
    await session.flush()
    return int(stream.id)


def recordings_for_stream(
    session: AsyncSession,
    stream_id: int,
    *,
    source: str = DEFAULT_SOURCE,
    available_only: bool = True,
):
    query = select(StreamRecording).where(
        StreamRecording.stream_id == stream_id,
        StreamRecording.source == source,
    )
    if available_only:
        query = query.where(StreamRecording.is_available.is_(True))
    return query.order_by(StreamRecording.id.asc())


async def urls_for_stream(
    session: AsyncSession,
    stream_id: int,
    *,
    source: str = DEFAULT_SOURCE,
    available_only: bool = True,
) -> list[str]:
    result = await session.execute(
        recordings_for_stream(
            session, stream_id, source=source, available_only=available_only
        )
    )
    return [recording.url for recording in result.scalars().all() if recording.url]


async def mark_missing_unavailable(
    session: AsyncSession,
    *,
    keep_urls: Iterable[str],
    keep_video_ids: Iterable[str] = (),
    source: str = DEFAULT_SOURCE,
) -> int:
    """Скрыть записи, которых больше нет в архиве Twitch. Не удаляет строки."""
    urls = {str(url).strip() for url in keep_urls if str(url or "").strip()}
    video_ids = {str(vid).strip() for vid in keep_video_ids if str(vid or "").strip()}

    result = await session.execute(
        select(StreamRecording).where(StreamRecording.source == source)
    )
    hidden = 0
    now = utcnow()
    for recording in result.scalars().all():
        if recording.url in urls:
            continue
        if recording.twitch_video_id and recording.twitch_video_id in video_ids:
            continue
        if recording.is_available is False:
            continue
        recording.is_available = False
        recording.updated_at = now
        hidden += 1
    return hidden


__all__ = [
    "DEFAULT_SOURCE",
    "ensure_stream",
    "fields_from_vod",
    "find_recording",
    "get_by_id",
    "link_recording_to_job",
    "mark_missing_unavailable",
    "parse_duration_minutes",
    "parse_video_id",
    "recordings_for_stream",
    "to_naive_utc",
    "upsert_from_vod",
    "upsert_recording",
    "urls_for_stream",
    "utcnow",
]
