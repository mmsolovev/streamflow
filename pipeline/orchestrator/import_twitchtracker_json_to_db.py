from __future__ import annotations

"""
Orchestrator job: import legacy TwitchTracker JSON (storage/streams.json + storage/games.json) into DB.
"""

import argparse
from pathlib import Path

from database.db import Base, SessionLocal, engine
from pipeline.ingest.twitchtracker_data import load_games_json, load_streams_json
from pipeline.load.twitchtracker_db_sync import sync_game_stats, sync_streams, update_streams_count


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def run(
    *,
    streams_path: Path | None = None,
    games_path: Path | None = None,
    dry_run: bool = False,
    prune: bool = True,
    sync_participants_from_title: bool = True,
) -> None:
    Base.metadata.create_all(bind=engine)

    root = _project_root()
    streams_path = Path(streams_path) if streams_path is not None else (root / "storage" / "streams.json")
    games_path = Path(games_path) if games_path is not None else (root / "storage" / "games.json")

    streams_data = load_streams_json(streams_path)
    games_data = load_games_json(games_path)

    session = SessionLocal()
    try:
        from database.models import Game

        game_cache = {game.name: game for game in session.query(Game).all()}

        stream_stats = sync_streams(
            session,
            streams_data,
            game_cache,
            prune_missing=bool(prune),
            sync_participants_from_title=bool(sync_participants_from_title),
        )
        game_stats = sync_game_stats(session, games_data, game_cache, prune_missing=bool(prune))
        streams_count_updated = update_streams_count(session)

        if dry_run:
            session.rollback()
        else:
            session.commit()

        print(
            f"Streams -> added: {stream_stats.added}, updated: {stream_stats.updated}, "
            f"unchanged: {stream_stats.unchanged}, deleted: {stream_stats.deleted}"
        )
        print(
            f"Game stats -> added: {game_stats.added}, updated: {game_stats.updated}, "
            f"unchanged: {game_stats.unchanged}, deleted: {game_stats.deleted}"
        )
        print(f"GameStats.streams_count updated rows: {streams_count_updated}")
        print("Dry run: yes" if dry_run else "Dry run: no")
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Import legacy streams.json + games.json into SQLite.")
    parser.add_argument("--dry-run", action="store_true", help="Do not write changes to DB.")
    parser.add_argument("--no-prune", action="store_true", help="Do not delete DB rows missing from JSON.")
    parser.add_argument("--no-sync-participants", action="store_true", help="Do not sync participants from @mentions.")
    parser.add_argument("--streams-path", default="", help="Path to streams.json (default: storage/streams.json).")
    parser.add_argument("--games-path", default="", help="Path to games.json (default: storage/games.json).")
    args = parser.parse_args()

    streams_path = Path(args.streams_path) if str(args.streams_path or "").strip() else None
    games_path = Path(args.games_path) if str(args.games_path or "").strip() else None

    run(
        streams_path=streams_path,
        games_path=games_path,
        dry_run=bool(args.dry_run),
        prune=not bool(args.no_prune),
        sync_participants_from_title=not bool(args.no_sync_participants),
    )


if __name__ == "__main__":
    main()

