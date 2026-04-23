from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any


@dataclass(frozen=True, slots=True)
class StreamForVodMatch:
    id: int
    date: datetime
    title: str | None


def _parse_vod_created_at(value: str) -> datetime:
    # Twitch returns ISO like "2026-01-01T12:34:56Z"
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def build_vods_index(vods: list[dict[str, Any]]) -> dict[date, list[dict[str, Any]]]:
    vods_by_date: dict[date, list[dict[str, Any]]] = defaultdict(list)

    for vod in vods:
        created_at = _parse_vod_created_at(vod.get("created_at"))
        vods_by_date[created_at.date()].append(vod)

    return dict(vods_by_date)


def is_match(stream: StreamForVodMatch, vod: dict[str, Any]) -> bool:
    vod_start = _parse_vod_created_at(vod.get("created_at"))

    # 1) Exact date match.
    if stream.date.date() == vod_start.date():
        return True

    # 2) Fallback: +-1 day + title overlap.
    delta_days = abs((stream.date.date() - vod_start.date()).days)
    if delta_days <= 1:
        s1 = (stream.title or "").strip().lower()
        s2 = str(vod.get("title") or "").strip().lower()
        if s1 and s2 and (s1 in s2 or s2 in s1):
            return True

    return False


def pick_vod_candidates(
    *,
    vods_by_date: dict[date, list[dict[str, Any]]],
    stream_date: date,
) -> list[dict[str, Any]]:
    candidates = vods_by_date.get(stream_date, [])
    if candidates:
        return candidates

    # +-1 day fallback if no exact bucket exists.
    return (vods_by_date.get(stream_date - timedelta(days=1), []) or []) + (
        vods_by_date.get(stream_date + timedelta(days=1), []) or []
    )

