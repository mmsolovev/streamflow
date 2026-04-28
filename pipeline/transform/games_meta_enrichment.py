from __future__ import annotations

"""
Transform layer: decide how to enrich games_meta fields and normalize text formats.
"""

from dataclasses import dataclass
from typing import Any


def normalize_key(value: str) -> str:
    return " ".join((value or "").casefold().split())


def is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def normalize_genre_token(token: str) -> str:
    if normalize_key(token) == "role-playing (rpg)":
        return "RPG"
    return token.strip()


def normalize_genres_text(genres_text: str | None) -> str | None:
    tokens = [normalize_genre_token(t) for t in parse_csv(genres_text)]
    seen: set[str] = set()
    out: list[str] = []
    for t in tokens:
        key = normalize_key(t)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(t)
    return ", ".join(out) if out else None


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
    "is_blank",
    "normalize_genres_text",
    "normalize_key",
]

