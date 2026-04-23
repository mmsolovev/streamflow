"""
Legacy script kept for backwards compatibility.

Old behavior: parse all TwitchTracker games HTML pages into storage/games.json.
New implementation delegates to pipeline ingest+delivery modules.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from pipeline.delivery.twitchtracker_json import write_games_json
from pipeline.ingest.twitchtracker_html import parse_game_pages


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse TwitchTracker games HTML pages into games.json.")
    parser.add_argument(
        "--pages-dir",
        default="",
        help="Path to directory with TwitchTracker HTML pages (default: storage/pages).",
    )
    parser.add_argument(
        "--out",
        default="",
        help="Output path for games.json (default: storage/games.json).",
    )
    args = parser.parse_args()

    root = _project_root()
    pages_dir = Path(args.pages_dir) if str(args.pages_dir or "").strip() else (root / "storage" / "pages")
    out = Path(args.out) if str(args.out or "").strip() else (root / "storage" / "games.json")

    games = parse_game_pages(pages_dir=pages_dir)
    write_games_json(out, games)
    print(f"games.json written: {out} (games={len(games)})")


if __name__ == "__main__":
    main()

