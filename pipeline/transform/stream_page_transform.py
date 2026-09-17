from __future__ import annotations

"""
Transform: stream-page domain.

Functions for matching TwitchTracker stream-page data to DB streams
and to Twitch VODs (for external_id extraction).
"""

from datetime import date, datetime
from typing import Any

from pipeline.ingest.twitchtracker_parser import StreamPageData
from pipeline.transform.streams_transform import (
    StreamForVodMatch,
    extract_stream_id_from_vod,
    is_match,
    pick_vod_candidates,
)
from pipeline.transform.utils_transform import normalize_key

_VOD_MATCH_WINDOW_HOURS = 6


def _naive_vod_created_at(vod: dict[str, Any]) -> datetime | None:
    raw = vod.get("created_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).replace(tzinfo=None)
    except (ValueError, TypeError):
        return None


def _page_vod_title_overlap(page: StreamPageData, vod: dict[str, Any]) -> bool:
    page_title = page.title_changes[0].title if page.title_changes else ""
    vod_title = vod.get("title") or ""
    a = normalize_key(page_title)
    b = normalize_key(vod_title)
    return bool(a and b and (a in b or b in a))


def build_stream_pages_index(pages: list[StreamPageData]) -> dict[date, StreamPageData]:
    """Index parsed stream pages by date (date-only key)."""
    index: dict[date, StreamPageData] = {}
    for page in pages:
        key = page.date.date() if isinstance(page.date, datetime) else page.date
        index[key] = page
    return index


def resolve_external_id(
    page: StreamPageData,
    vods_by_date: dict[date, list[dict[str, Any]]],
) -> str | None:
    """Find Twitch stream_id from matching VOD, or None if no VOD match.

    When several VODs exist for the same day (multiple streams), prefer the
    one whose start time is nearest to page.started_at and, ideally, whose
    title overlaps the stream title. Falls back to legacy date/title matching.
    """
    stream_date = page.date.date() if isinstance(page.date, datetime) else page.date

    candidates = pick_vod_candidates(vods_by_date=vods_by_date, stream_date=stream_date)

    if page.started_at:
        scored = []
        for vod in candidates:
            created = _naive_vod_created_at(vod)
            if created is None:
                continue
            minutes = abs((created - page.started_at).total_seconds()) / 60.0
            scored.append((minutes, _page_vod_title_overlap(page, vod), vod))

        if scored:
            window_minutes = _VOD_MATCH_WINDOW_HOURS * 60
            scored.sort(key=lambda item: (item[0] > window_minutes, not item[1], item[0]))
            best_minutes, _, best = scored[0]
            if best_minutes <= window_minutes or _page_vod_title_overlap(page, best):
                best_id = extract_stream_id_from_vod(best)
                if best_id:
                    return best_id

    stream_for_match = StreamForVodMatch(
        id=0,
        date=datetime.combine(stream_date, datetime.min.time()),
        title=page.title_changes[0].title if page.title_changes else "",
    )

    for vod in candidates:
        if is_match(stream_for_match, vod):
            return extract_stream_id_from_vod(vod)
    return None


__all__ = [
    "build_stream_pages_index",
    "resolve_external_id",
]
