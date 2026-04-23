"""
Legacy script kept for backwards compatibility.

Old behavior: parse all TwitchTracker stream HTML pages into storage/streams.json.
New implementation delegates to pipeline ingest+delivery modules.

Prefer: `python pipeline/runtime/sync_twitchtracker_html_to_db.py --write-json --merge-json`
if you want both DB sync and JSON mirroring.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from pipeline.delivery.twitchtracker_json import write_streams_json
from pipeline.ingest.twitchtracker_html import parse_stream_pages


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse TwitchTracker streams HTML pages into streams.json.")
    parser.add_argument(
        "--pages-dir",
        default="",
        help="Path to directory with TwitchTracker HTML pages (default: storage/pages).",
    )
    parser.add_argument(
        "--out",
        default="",
        help="Output path for streams.json (default: storage/streams.json).",
    )
    parser.add_argument(
        "--merge",
        action="store_true",
        help="Merge into existing streams.json instead of overwriting.",
    )
    args = parser.parse_args()

    root = _project_root()
    pages_dir = Path(args.pages_dir) if str(args.pages_dir or "").strip() else (root / "storage" / "pages")
    out = Path(args.out) if str(args.out or "").strip() else (root / "storage" / "streams.json")

    streams = parse_stream_pages(pages_dir=pages_dir)
    write_streams_json(out, streams, merge_existing=bool(args.merge))
    print(f"streams.json written: {out} (streams={len(streams)}, merge={bool(args.merge)})")


if __name__ == "__main__":
    main()

