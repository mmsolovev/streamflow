from __future__ import annotations

"""
Orchestrator: new stream HTML -> merge into storage/streams.json.

ingest -> delivery (merge_existing)
"""

import json
from datetime import datetime
from pathlib import Path

from pipeline.delivery.json_twitchtracker import write_streams_json
from pipeline.ingest.twitchtracker_parser import parse_stream_file


def _fmt_stream_date(dt: datetime) -> str:
    return dt.strftime("%d/%b/%Y %H:%M")


def _default_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _streams_index_by_date(path: Path) -> dict[str, dict]:
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, list):
        return {}
    out: dict[str, dict] = {}
    for row in data:
        if isinstance(row, dict):
            key = str(row.get("date") or "").strip()
            if key:
                out[key] = row
    return out


def run() -> int:
    root = _default_project_root()
    html_path = root / "storage" / "pages" / "new_stream_page.html"
    out_path = root / "storage" / "streams.json"

    before = _streams_index_by_date(out_path)

    rows = parse_stream_file(path=html_path)
    if not rows:
        print(f"No stream rows parsed from {html_path}")
        return 1

    write_streams_json(out_path, rows, merge_existing=True)

    keys = {_fmt_stream_date(r.date) for r in rows}
    added = len(keys - before.keys())
    updated = len(keys & before.keys())
    print(f"Streams merged into {out_path}: added {added}, updated {updated}, parsed {len(rows)} row(s)")

    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
