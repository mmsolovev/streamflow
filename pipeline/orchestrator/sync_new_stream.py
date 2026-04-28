from __future__ import annotations

"""
Orchestrator scenario: sync a single new stream into DB.

Inputs:
- one TwitchTracker HTML file for the new stream
- one TwitchTracker HTML file with "all games" stats (to update games_stats)

Optional:
- mirror datasets into JSON as a backup collection format
- recompute genres_text for the newly added/updated stream
"""

import argparse
from pathlib import Path

from database.db import Base, SessionLocal, engine
from pipeline.delivery.twitchtracker_json import write_games_json, write_streams_json
from pipeline.ingest.twitchtracker_data import parse_game_file, parse_stream_file
from pipeline.load.twitchtracker_db_sync import sync_game_stats, sync_streams, update_streams_count
from pipeline.orchestrator.enrich_streams_genres import run as run_enrich_stream_genres


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _pick_latest_games_file(pages_dir: Path) -> Path | None:
    pages_dir = Path(pages_dir)
    if not pages_dir.exists():
        return None
    candidates = [p for p in pages_dir.iterdir() if p.is_file() and p.name.startswith("games_page") and p.suffix == ".html"]
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.name)
    return candidates[-1]


def run(
    *,
    stream_html: Path,
    games_html: Path | None = None,
    pages_dir: Path | None = None,
    dry_run: bool = False,
    write_json: bool = False,
    merge_streams_json: bool = True,
    streams_json_path: Path | None = None,
    games_json_path: Path | None = None,
    update_genres_for_stream: bool = True,
) -> None:
    Base.metadata.create_all(bind=engine)

    stream_html = Path(stream_html)
    if not stream_html.exists():
        raise SystemExit(f"stream_html not found: {stream_html}")

    if games_html is None:
        if pages_dir is None:
            pages_dir = _project_root() / "storage" / "pages"
        games_html = _pick_latest_games_file(Path(pages_dir))
        if games_html is None:
            raise SystemExit("games_html not provided and no games_page*.html found in pages_dir.")

    games_html = Path(games_html)
    if not games_html.exists():
        raise SystemExit(f"games_html not found: {games_html}")

    streams_data = parse_stream_file(path=stream_html)
    if not streams_data:
        raise SystemExit(f"No streams parsed from: {stream_html}")

    # For "sync new stream" we expect one stream row; if there are multiple, take the latest.
    stream_row = sorted(streams_data, key=lambda s: s.date)[-1]
    streams_data = [stream_row]

    games_data = parse_game_file(path=games_html)

    if write_json:
        root = _project_root()
        streams_path = Path(streams_json_path) if streams_json_path is not None else (root / "storage" / "streams.json")
        games_path = Path(games_json_path) if games_json_path is not None else (root / "storage" / "games.json")
        write_streams_json(streams_path, streams_data, merge_existing=bool(merge_streams_json))
        if games_data:
            write_games_json(games_path, games_data)

    session = SessionLocal()
    try:
        from database.models import Game, Stream

        game_cache = {game.name: game for game in session.query(Game).all()}

        stream_stats = sync_streams(session, streams_data, game_cache, prune_missing=False)
        game_stats = sync_game_stats(session, games_data, game_cache, prune_missing=False) if games_data else None
        streams_count_updated = update_streams_count(session)

        # Identify the target stream row (by external_id = iso date).
        external_id = stream_row.date.isoformat()
        stream_obj = session.query(Stream).filter(Stream.external_id == external_id).one_or_none()
        stream_id = int(stream_obj.id) if stream_obj is not None else 0

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
        if game_stats is not None:
            print(
                f"Game stats -> added: {game_stats.added}, "
                f"updated: {game_stats.updated}, "
                f"unchanged: {game_stats.unchanged}, "
                f"deleted: {game_stats.deleted}"
            )
        print(f"GameStats.streams_count updated rows: {streams_count_updated}")
        print(f"Target stream external_id={external_id} stream_id={stream_id or 'n/a'}")
        print("Dry run: yes" if dry_run else "Dry run: no")
    finally:
        session.close()

    if update_genres_for_stream and not dry_run:
        # Re-run in a separate session after commit.
        if stream_id:
            run_enrich_stream_genres(dry_run=False, only_stream_id=int(stream_id), force=True, limit=0)
        else:
            print("Skip genres recompute: could not resolve stream_id.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync a single new stream HTML file into DB.")
    parser.add_argument("--stream-html", required=True, help="Path to the TwitchTracker HTML file for the new stream.")
    parser.add_argument("--games-html", default="", help="Path to TwitchTracker games_page HTML (all games).")
    parser.add_argument("--pages-dir", default="", help="Directory to auto-pick latest games_page*.html if --games-html is not set.")
    parser.add_argument("--dry-run", action="store_true", help="Do not commit changes to DB.")
    parser.add_argument("--write-json", action="store_true", help="Also mirror data into storage/*.json as a backup.")
    parser.add_argument("--no-merge-streams-json", action="store_true", help="Overwrite streams.json instead of merging.")
    parser.add_argument("--streams-json-path", default="", help="Override output path for streams.json.")
    parser.add_argument("--games-json-path", default="", help="Override output path for games.json.")
    parser.add_argument("--no-update-genres", action="store_true", help="Do not recompute genres_text for the stream.")
    args = parser.parse_args()

    games_html = Path(args.games_html) if str(args.games_html or "").strip() else None
    pages_dir = Path(args.pages_dir) if str(args.pages_dir or "").strip() else None
    streams_json_path = Path(args.streams_json_path) if str(args.streams_json_path or "").strip() else None
    games_json_path = Path(args.games_json_path) if str(args.games_json_path or "").strip() else None

    run(
        stream_html=Path(args.stream_html),
        games_html=games_html,
        pages_dir=pages_dir,
        dry_run=bool(args.dry_run),
        write_json=bool(args.write_json),
        merge_streams_json=not bool(args.no_merge_streams_json),
        streams_json_path=streams_json_path,
        games_json_path=games_json_path,
        update_genres_for_stream=not bool(args.no_update_genres),
    )


if __name__ == "__main__":
    main()

