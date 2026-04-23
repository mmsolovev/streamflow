from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pipeline.ingest.twitchtracker_html import TwitchTrackerGameRow, TwitchTrackerStreamRow


def _parse_stream_date(value: str) -> datetime:
    return datetime.strptime(value, "%d/%b/%Y %H:%M")


def _parse_game_last_stream(value: str) -> datetime:
    return datetime.strptime(value, "%d/%b/%Y")


def _clean_int(value: Any) -> int:
    return int(str(value).replace(",", "").strip())


def _clean_float(value: Any) -> float:
    return float(str(value).replace(",", "").strip())


def _clean_duration_hours(value: Any) -> float:
    # legacy streams.json uses strings like "3.5hrs"
    s = str(value).strip().replace(" ", "")
    if s.endswith("hrs"):
        s = s[: -3]
    return float(s)


def load_streams_json(path: Path) -> list[TwitchTrackerStreamRow]:
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError(f"Expected list in streams.json: {path}")

    out: list[TwitchTrackerStreamRow] = []
    for item in rows:
        if not isinstance(item, dict):
            continue

        out.append(
            TwitchTrackerStreamRow(
                date=_parse_stream_date(str(item.get("date") or "")),
                duration_hours=_clean_duration_hours(item.get("duration")),
                avg_viewers=_clean_int(item.get("avg_viewers")),
                max_viewers=_clean_int(item.get("max_viewers")),
                followers=_clean_int(item.get("followers")),
                views=_clean_int(item.get("views")),
                title=str(item.get("title") or ""),
                games=[str(x) for x in (item.get("games") or []) if str(x).strip()],
            )
        )

    out.sort(key=lambda x: x.date)
    return out


def load_games_json(path: Path) -> list[TwitchTrackerGameRow]:
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError(f"Expected list in games.json: {path}")

    out: list[TwitchTrackerGameRow] = []
    for item in rows:
        if not isinstance(item, dict):
            continue

        out.append(
            TwitchTrackerGameRow(
                name=str(item.get("game") or ""),
                rank=_clean_int(item.get("rank")),
                hours_streamed=_clean_float(item.get("hours_streamed")),
                avg_viewers=_clean_int(item.get("avg_viewers")),
                max_viewers=_clean_int(item.get("max_viewers")),
                followers_per_hour=_clean_float(item.get("followers_per_hour")),
                last_stream=_parse_game_last_stream(str(item.get("last_stream") or "")),
            )
        )

    out.sort(key=lambda x: (x.rank, x.name.casefold()))
    return out

