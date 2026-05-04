from __future__ import annotations

"""
Transform layer: games domain.

Contains enrichment decision logic for GameMeta (which fields to fill).
IGDB payload parsing lives in pipeline.transform.igdb_transform.
"""

from dataclasses import dataclass
from typing import Any

from pipeline.transform.utils_transform import is_blank, normalize_genres_text


@dataclass(frozen=True, slots=True)
class GamesMetaRowView:
    game_id: int
    game_name: str
    hltb_hours: float | None
    steam_url: str | None
    platforms_text: str | None
    genres_text: str | None


@dataclass(frozen=True, slots=True)
class IgdbMetaView:
    steam_url: str | None
    platforms_text: str | None
    genres_text: str | None


def build_patch(
    row: GamesMetaRowView,
    *,
    hltb_hours: float | None,
    igdb: IgdbMetaView | None,
) -> dict[str, Any]:
    patch: dict[str, Any] = {}

    want_hltb = row.hltb_hours is None or float(row.hltb_hours or 0) <= 0
    want_steam = is_blank(row.steam_url)
    want_platforms = is_blank(row.platforms_text)
    want_genres = is_blank(row.genres_text)

    if want_hltb and isinstance(hltb_hours, (int, float)) and float(hltb_hours) > 0:
        patch["hltb_hours"] = float(hltb_hours)

    if igdb is not None:
        if want_steam and igdb.steam_url:
            patch["steam_url"] = str(igdb.steam_url).strip() or None
        if want_platforms and igdb.platforms_text:
            patch["platforms_text"] = str(igdb.platforms_text).strip() or None
        if want_genres and igdb.genres_text:
            patch["genres_text"] = normalize_genres_text(str(igdb.genres_text))

    return patch


__all__ = [
    "GamesMetaRowView",
    "IgdbMetaView",
    "build_patch",
]
