from __future__ import annotations

"""
Transform layer: compute Stream.genres_text from:
- fixed rules based on title / participants / game list
- genres_text from related games_meta rows
"""

import re
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


def dedup_keep_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        key = normalize_key(v)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(v)
    return out


def compute_stream_genres(
    *,
    title: str | None,
    has_participants: bool,
    game_names: list[str],
    game_genres_texts: list[str | None],
) -> str | None:
    title_raw = title or ""
    title_norm = normalize_key(title_raw)
    token_list = [t for t in re.findall(r"[\w@]+", title_raw, flags=re.UNICODE) if t]
    title_tokens = {normalize_key(t) for t in token_list}
    tags: list[str] = []

    # Rule: if the only game is Just Chatting -> "Общение"
    names_norm = [normalize_key(n) for n in game_names if n]
    if len(names_norm) == 1 and names_norm[0] == "just chatting":
        tags.append("Общение")

    # Rule: streams with participants -> "Кооп"
    if has_participants:
        tags.append("Кооп")

    # Rule: keywords in title
    if {"ирл", "кирл", "irl"} & title_tokens:
        tags.append("IRL")
    if "кукинг" in title_tokens or "кукинг" in title_norm:
        tags.append("Кукинг")

    # Genres from games
    game_genres: list[str] = []
    for gt in game_genres_texts:
        for token in parse_csv(gt):
            token = normalize_genre_token(token)
            if token:
                game_genres.append(token)
    game_genres = dedup_keep_order(game_genres)

    # Desired order:
    fixed_order = ["Общение", "Кооп", "Кукинг", "IRL"]
    fixed = [t for t in fixed_order if any(normalize_key(x) == normalize_key(t) for x in tags)]
    rest = [g for g in game_genres if normalize_key(g) not in {normalize_key(t) for t in fixed}]
    rest = sorted(rest, key=lambda x: x.casefold())

    result = dedup_keep_order(fixed + rest)
    return ", ".join(result) if result else None


__all__ = [
    "compute_stream_genres",
    "dedup_keep_order",
    "is_blank",
    "normalize_genre_token",
    "normalize_key",
    "parse_csv",
]

