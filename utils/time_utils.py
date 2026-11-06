"""Единое время проекта: TwitchTracker отдаёт локальное, БД хранит UTC.

`streams`, `stream_titles`, записи и runtime-сессии — naive UTC. TwitchTracker
показывает время канала без зоны, поэтому все его timestamp-поля прогоняются
через `tracker_to_utc`, а обратно (для отображения/сравнения с TT) —
через `utc_to_tracker`.

`parse_stream_date` (дата-ключ legacy-импорта) сознательно не трогаем: от неё
зависит `streams.external_id` старых строк. Конвертируется только то, что
попадает в БД как момент времени.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache

import config.settings as settings

# Запасной вариант, если в системе нет IANA-базы (Windows без пакета tzdata).
_FALLBACK_OFFSETS = {
    "UTC": 0,
    "Etc/UTC": 0,
    "Europe/Moscow": 3,
    "Europe/Kiev": 2,
    "Europe/Kyiv": 2,
}


@lru_cache(maxsize=4)
def tracker_timezone():
    """Часовой пояс TwitchTracker (`TWITCHTRACKER_TIMEZONE`)."""
    name = (settings.TWITCHTRACKER_TIMEZONE or "Europe/Moscow").strip()
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:  # ZoneInfoNotFoundError и отсутствие tzdata
        hours = _FALLBACK_OFFSETS.get(name)
        if hours is None:
            print(
                f"WARNING: timezone {name!r} is unavailable, assuming Europe/Moscow (+3)"
            )
            hours = 3
        return timezone(timedelta(hours=hours))


def tracker_to_utc(value: datetime | None) -> datetime | None:
    """Naive-время канала -> naive UTC. Aware-значение просто приводится к UTC."""
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.replace(tzinfo=tracker_timezone()).astimezone(timezone.utc).replace(
        tzinfo=None
    )


def utc_to_tracker(value: datetime | None) -> datetime | None:
    """Naive UTC -> naive-время канала (для сверки с TwitchTracker)."""
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(tracker_timezone()).replace(tzinfo=None)


__all__ = [
    "tracker_timezone",
    "tracker_to_utc",
    "utc_to_tracker",
]
