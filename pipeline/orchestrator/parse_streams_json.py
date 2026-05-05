from __future__ import annotations

"""
Orchestrator: new stream HTML -> merge into storage/streams.json.

ingest -> delivery (merge_existing)
"""

import argparse
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


def run(
    *,
    project_root: Path | None = None,
    stream_html: Path | None = None,
    streams_json: Path | None = None,
    merge_existing: bool = True,
) -> int:
    root = Path(project_root) if project_root is not None else _default_project_root()
    html_path = Path(stream_html) if stream_html is not None else root / "storage" / "pages" / "new_stream_page.html"
    out_path = Path(streams_json) if streams_json is not None else root / "storage" / "streams.json"

    before = _streams_index_by_date(out_path) if merge_existing else {}

    rows = parse_stream_file(path=html_path)
    if not rows:
        print(f"No stream rows parsed from {html_path}")
        return 1

    write_streams_json(out_path, rows, merge_existing=merge_existing)

    if merge_existing:
        keys = {_fmt_stream_date(r.date) for r in rows}
        added = len(keys - before.keys())
        updated = len(keys & before.keys())
        print(f"Streams merged into {out_path}: added {added}, updated {updated}, parsed {len(rows)} row(s)")
    else:
        print(f"Wrote {len(rows)} stream(s) to {out_path} (no merge)")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse TwitchTracker stream HTML into streams.json")
    parser.add_argument(
        "--html",
        type=Path,
        default=None,
        dest="stream_html",
        help="Stream HTML file (default: <project>/storage/pages/new_stream_page.html)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        dest="streams_json",
        help="streams.json path (default: <project>/storage/streams.json)",
    )
    parser.add_argument(
        "--no-merge",
        action="store_true",
        help="Replace file instead of merging with existing streams.json",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Project root for default paths (default: inferred from this file)",
    )
    args = parser.parse_args()
    raise SystemExit(
        run(
            project_root=args.project_root,
            stream_html=args.stream_html,
            streams_json=args.streams_json,
            merge_existing=not args.no_merge,
        )
    )


if __name__ == "__main__":
    main()
