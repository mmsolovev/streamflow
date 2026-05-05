from __future__ import annotations

"""
Orchestrator: games_page*.html -> storage/games.json (full replace).

ingest -> transform -> delivery
"""

import argparse
from pathlib import Path

from pipeline.delivery.json_twitchtracker import write_games_json
from pipeline.ingest.twitchtracker_parser import collect_game_rows_from_pages_dir
from pipeline.transform.twitchtracker_transform import merge_twitchtracker_game_rows


def _default_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def run(
    *,
    project_root: Path | None = None,
    pages_dir: Path | None = None,
    games_json: Path | None = None,
) -> int:
    root = Path(project_root) if project_root is not None else _default_project_root()
    pages = Path(pages_dir) if pages_dir is not None else root / "storage" / "pages"
    out_path = Path(games_json) if games_json is not None else root / "storage" / "games.json"

    raw = collect_game_rows_from_pages_dir(pages_dir=pages)
    games = merge_twitchtracker_game_rows(raw)
    write_games_json(out_path, games)
    print(f"Wrote {len(games)} games to {out_path}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Parse TwitchTracker games HTML into games.json")
    parser.add_argument(
        "--pages-dir",
        type=Path,
        default=None,
        help="Directory with games_page*.html (default: <project>/storage/pages)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        dest="games_json",
        help="Output JSON path (default: <project>/storage/games.json)",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=None,
        help="Project root for default paths (default: inferred from this file)",
    )
    args = parser.parse_args()
    raise SystemExit(
        run(project_root=args.project_root, pages_dir=args.pages_dir, games_json=args.games_json)
    )


if __name__ == "__main__":
    main()
