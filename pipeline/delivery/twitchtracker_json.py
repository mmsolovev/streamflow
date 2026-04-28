from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pipeline.ingest.twitchtracker_data import TwitchTrackerGameRow, TwitchTrackerStreamRow, parse_stream_date


def _fmt_stream_date(dt: datetime) -> str:
    # Historical format used by older html->json scripts and import_json_to_db.py.
    return dt.strftime("%d/%b/%Y %H:%M")


def _fmt_game_last_stream(dt: datetime) -> str:
    # Historical format used by older twitchtracker_games_parser.py and import_json_to_db.py.
    return dt.strftime("%d/%b/%Y")


def _fmt_duration_hours(value: float) -> str:
    # Older pipeline used strings like "3.5hrs".
    s = f"{float(value):.4f}".rstrip("0").rstrip(".")
    return f"{s}hrs"


def _atomic_write_text(path: Path, text: str, *, encoding: str = "utf-8") -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding=encoding)
    tmp.replace(path)


def _load_json_list(path: Path) -> list[Any]:
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _parse_stream_date_str(value: str) -> datetime:
    # Keep local wrapper for backward-compat with existing call sites in this module.
    return parse_stream_date(value)


def write_streams_json(path: Path, streams: list[TwitchTrackerStreamRow], *, merge_existing: bool = False) -> None:
    new_rows: list[dict[str, Any]] = []
    for s in streams:
        new_rows.append(
            {
                "date": _fmt_stream_date(s.date),
                "duration": _fmt_duration_hours(s.duration_hours),
                "avg_viewers": int(s.avg_viewers),
                "max_viewers": int(s.max_viewers),
                "followers": int(s.followers),
                "views": int(s.views),
                "title": s.title,
                "games": list(s.games),
            }
        )

    if merge_existing:
        existing_rows = _load_json_list(Path(path))
        by_date: dict[str, dict[str, Any]] = {}
        for row in existing_rows:
            if not isinstance(row, dict):
                continue
            key = str(row.get("date") or "").strip()
            if key:
                by_date[key] = row

        for row in new_rows:
            key = str(row.get("date") or "").strip()
            if key:
                by_date[key] = row

        def sort_key(item: dict[str, Any]) -> datetime:
            try:
                return _parse_stream_date_str(str(item.get("date") or ""))
            except ValueError:
                return datetime.min

        out = sorted(by_date.values(), key=sort_key)
    else:
        out = new_rows

    text = json.dumps(out, ensure_ascii=False, indent=2)
    _atomic_write_text(Path(path), text + "\n")


def write_games_json(path: Path, games: list[TwitchTrackerGameRow]) -> None:
    out: list[dict[str, Any]] = []
    for g in games:
        out.append(
            {
                "rank": int(g.rank),
                "game": g.name,
                "hours_streamed": float(g.hours_streamed),
                "avg_viewers": int(g.avg_viewers),
                "max_viewers": int(g.max_viewers),
                "followers_per_hour": float(g.followers_per_hour),
                "last_stream": _fmt_game_last_stream(g.last_stream),
            }
        )

    text = json.dumps(out, ensure_ascii=False, indent=2)
    _atomic_write_text(Path(path), text + "\n")
