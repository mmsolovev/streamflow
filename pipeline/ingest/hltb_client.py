from __future__ import annotations

"""
Ingest layer: fetch playtime estimate from HowLongToBeat.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HltbResult:
    hltb_hours: float
    matched_name: str
    similarity: float


def search_best(game_name: str, *, min_similarity: float) -> HltbResult | None:
    # Lazy imports so the project can still run without optional deps.
    import re

    from howlongtobeatpy import HowLongToBeat

    def sanitize(value: str) -> str:
        sanitized = re.sub(r"[^\w\s:+'\-.]", " ", value, flags=re.UNICODE)
        return " ".join(sanitized.split())

    client = HowLongToBeat()
    queries = [game_name]
    sanitized = sanitize(game_name)
    if sanitized and sanitized != game_name:
        queries.append(sanitized)

    best_match = None
    best_similarity = 0.0

    for q in queries:
        results = client.search(q) or []
        for r in results:
            sim = float(getattr(r, "similarity", 0.0) or 0.0)
            if sim > best_similarity:
                best_match = r
                best_similarity = sim

    if best_match is None or best_similarity < float(min_similarity):
        return None

    hours = getattr(best_match, "all_styles", None)
    if hours is None:
        return None

    return HltbResult(
        hltb_hours=float(hours),
        matched_name=str(getattr(best_match, "game_name", "") or ""),
        similarity=float(best_similarity),
    )


__all__ = ["HltbResult", "search_best"]

