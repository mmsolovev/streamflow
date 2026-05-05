from __future__ import annotations

"""
Transform: merge duplicate TwitchTracker game rows (same name across HTML pages).

Policy matches legacy collector/twitchtracker_games_parser.py:
prefer later last_stream, then higher hours_streamed, then lower rank.
"""

from pipeline.ingest.twitchtracker_parser import TwitchTrackerGameRow


def merge_twitchtracker_game_rows(rows: list[TwitchTrackerGameRow]) -> list[TwitchTrackerGameRow]:
    by_name: dict[str, TwitchTrackerGameRow] = {}
    for row in rows:
        existing = by_name.get(row.name)
        if existing is None:
            by_name[row.name] = row
            continue
        by_name[row.name] = _choose_preferred_game_row(existing, row)
    return sorted(by_name.values(), key=lambda x: (x.rank, x.name.casefold()))


def _choose_preferred_game_row(current: TwitchTrackerGameRow, candidate: TwitchTrackerGameRow) -> TwitchTrackerGameRow:
    if candidate.last_stream != current.last_stream:
        return candidate if candidate.last_stream > current.last_stream else current
    if candidate.hours_streamed != current.hours_streamed:
        return candidate if candidate.hours_streamed > current.hours_streamed else current
    return candidate if candidate.rank < current.rank else current


__all__ = ["merge_twitchtracker_game_rows"]
