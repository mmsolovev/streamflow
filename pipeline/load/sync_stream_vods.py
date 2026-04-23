from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from database.models import Stream
from pipeline.transform.vod_matching import StreamForVodMatch, build_vods_index, is_match, pick_vod_candidates


@dataclass(frozen=True, slots=True)
class VodSyncStats:
    removed_outdated: int
    matched_new: int


def sync_stream_vod_urls(session: Session, vods: list[dict[str, Any]]) -> VodSyncStats:
    """
    Updates Stream.vod_url in-place:
    - clears stale vod_url values not present in fetched VODs
    - fills missing vod_url values by matching date (+-1 day fallback) and title overlap

    Commit/rollback is responsibility of the caller.
    """
    vod_urls = {str(v.get("url") or "").strip() for v in vods}
    vod_urls.discard("")

    vods_by_date = build_vods_index(vods)

    removed = 0
    streams_with_vods = session.query(Stream).filter(Stream.vod_url.isnot(None)).all()
    for stream in streams_with_vods:
        if stream.vod_url and stream.vod_url not in vod_urls:
            stream.vod_url = None
            removed += 1

    matched = 0
    streams_without_vods = session.query(Stream).filter(Stream.vod_url.is_(None)).all()
    for stream in streams_without_vods:
        if not stream.date:
            continue

        stream_view = StreamForVodMatch(id=int(stream.id), date=stream.date, title=stream.title)
        candidates = pick_vod_candidates(vods_by_date=vods_by_date, stream_date=stream.date.date())

        for vod in candidates:
            if is_match(stream_view, vod):
                url = str(vod.get("url") or "").strip()
                if url:
                    stream.vod_url = url
                    matched += 1
                break

    return VodSyncStats(removed_outdated=removed, matched_new=matched)

