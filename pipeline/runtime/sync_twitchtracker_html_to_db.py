from __future__ import annotations

import argparse
from pathlib import Path

from database.db import Base, SessionLocal, engine
from pipeline.delivery.twitchtracker_json import write_games_json, write_streams_json
from pipeline.ingest.twitchtracker_html import parse_game_pages, parse_stream_pages
from pipeline.load.twitchtracker_db_sync import sync_game_stats, sync_streams
from pipeline.load.update_streams_count import update_streams_count


def _project_root() -> Path:
    # .../pipeline/runtime/sync_twitchtracker_html_to_db.py -> project root
    return Path(__file__).resolve().parents[2]


def run(
    *,
    dry_run: bool = False,
    prune: bool = False,
    pages_dir: Path | None = None,
    write_json: bool = False,
    merge_json: bool = False,
    streams_json_path: Path | None = None,
    games_json_path: Path | None = None,
) -> None:
    Base.metadata.create_all(bind=engine)

    pages_dir = Path(pages_dir) if pages_dir is not None else (_project_root() / "storage" / "pages")
    streams_data = parse_stream_pages(pages_dir=pages_dir)
    games_data = parse_game_pages(pages_dir=pages_dir)

    if write_json:
        root = _project_root()
        streams_path = Path(streams_json_path) if streams_json_path is not None else (root / "storage" / "streams.json")
        games_path = Path(games_json_path) if games_json_path is not None else (root / "storage" / "games.json")
        write_streams_json(streams_path, streams_data, merge_existing=merge_json)
        write_games_json(games_path, games_data)

    session = SessionLocal()
    try:
        from database.models import Game

        game_cache = {game.name: game for game in session.query(Game).all()}

        stream_stats = sync_streams(session, streams_data, game_cache, prune_missing=prune)
        game_stats = sync_game_stats(session, games_data, game_cache, prune_missing=prune)
        streams_count_updated = update_streams_count(session)

        if dry_run:
            session.rollback()
        else:
            session.commit()

        print(
            f"Streams -> added: {stream_stats.added}, "
            f"updated: {stream_stats.updated}, "
            f"unchanged: {stream_stats.unchanged}, "
            f"deleted: {stream_stats.deleted}"
        )
        print(
            f"Game stats -> added: {game_stats.added}, "
            f"updated: {game_stats.updated}, "
            f"unchanged: {game_stats.unchanged}, "
            f"deleted: {game_stats.deleted}"
        )
        print(f"GameStats.streams_count updated rows: {streams_count_updated}")
        print("Dry run: yes" if dry_run else "Dry run: no")
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sync TwitchTracker HTML pages into SQLite (and optionally mirror to JSON)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and compare data without writing changes to the database.",
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        help="Delete DB rows that are missing in the parsed HTML dataset.",
    )
    parser.add_argument(
        "--pages-dir",
        default="",
        help="Path to directory with TwitchTracker HTML pages (default: storage/pages).",
    )
    parser.add_argument(
        "--write-json",
        action="store_true",
        help="Also write parsed datasets to storage/streams.json and storage/games.json.",
    )
    parser.add_argument(
        "--merge-json",
        action="store_true",
        help="When writing streams.json, merge into existing file instead of overwriting.",
    )
    parser.add_argument(
        "--streams-json-path",
        default="",
        help="Override output path for streams.json (requires --write-json).",
    )
    parser.add_argument(
        "--games-json-path",
        default="",
        help="Override output path for games.json (requires --write-json).",
    )
    args = parser.parse_args()

    pages_dir = Path(args.pages_dir) if str(args.pages_dir or "").strip() else None
    streams_json_path = Path(args.streams_json_path) if str(args.streams_json_path or "").strip() else None
    games_json_path = Path(args.games_json_path) if str(args.games_json_path or "").strip() else None

    run(
        dry_run=bool(args.dry_run),
        prune=bool(args.prune),
        pages_dir=pages_dir,
        write_json=bool(args.write_json),
        merge_json=bool(args.merge_json),
        streams_json_path=streams_json_path,
        games_json_path=games_json_path,
    )


if __name__ == "__main__":
    main()
