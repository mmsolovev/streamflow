from __future__ import annotations

"""
Orchestrator: games_page*.html -> storage/games.json (full replace).

ingest -> transform -> delivery
"""

from pathlib import Path

from pipeline.delivery.json_twitchtracker import write_games_json
from pipeline.ingest.twitchtracker_parser import collect_game_rows_from_pages_dir
from pipeline.transform.twitchtracker_transform import merge_twitchtracker_game_rows


def _default_project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def run() -> int:
    root = _default_project_root()
    pages = root / "storage" / "pages"
    out_path = root / "storage" / "games.json"

    raw = collect_game_rows_from_pages_dir(pages_dir=pages)
    games = merge_twitchtracker_game_rows(raw)
    write_games_json(out_path, games)
    print(f"Wrote {len(games)} games to {out_path}")
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
