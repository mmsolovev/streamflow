from __future__ import annotations

"""
Orchestrator job: sync one new stream into DB.
"""

from pathlib import Path

from database.models import Game
from pipeline.delivery.json_twitchtracker import write_games_json, write_streams_json
from pipeline.ingest.twitchtracker_parser import parse_game_file, parse_stream_file
from pipeline.load.load_game_stats import sync_game_stats
from pipeline.load.load_streams import sync_streams
from .context import PipelineContext


def run(
    context: PipelineContext,
    *,
    stream_html: Path,
    games_html: Path | None = None,
    pages_dir: Path | None = None,
    write_json: bool = False,
    merge_streams_json: bool = True,
    streams_json_path: Path | None = None,
    games_json_path: Path | None = None,
    update_genres_for_stream: bool = True,
) -> None:
    """
    Args:
        context: The pipeline context.
        stream_html: Path to the HTML file for the new stream.
        games_html: Path to the games page HTML. If empty, auto-picks from `pages_dir`.
        pages_dir: Directory to auto-pick the latest games_page*.html.
        write_json: Also mirror into `storage/*.json` as a backup.
        merge_streams_json: Merge into streams.json instead of overwriting.
        streams_json_path: Override output path for streams.json.
        games_json_path: Override output path for games.json.
        update_genres_for_stream: Recompute genres_text for the new stream.
    """
    if context.db_session is None:
        raise ValueError("DB session not initialized. Use `with PipelineContext(...)`.")

    # Set default paths
    pages_dir = pages_dir if pages_dir is not None else (context.project_root / "storage" / "pages")
    streams_json_path = streams_json_path if streams_json_path is not None else (context.project_root / "storage" / "streams.json")
    games_json_path = games_json_path if games_json_path is not None else (context.project_root / "storage" / "games.json")

    # Auto-find latest games HTML if not provided
    if games_html is None and pages_dir.exists():
        game_files = sorted(pages_dir.glob("games_page*.html"), reverse=True)
        if game_files:
            games_html = game_files[0]
            print(f"Auto-selected latest games HTML: {games_html.name}")

    # INGEST
    print(f"Parsing new stream from {stream_html.name}...")
    new_streams_data = parse_stream_file(path=stream_html)
    if not new_streams_data:
        print("No stream data found in the provided HTML file.")
        return

    games_data = []
    if games_html and games_html.exists():
        print(f"Parsing games from {games_html.name}...")
        games_data = parse_game_file(path=games_html)

    # DELIVERY (optional backup)
    if write_json:
        print("Writing to JSON files...")
        write_streams_json(streams_json_path, new_streams_data, merge_existing=merge_streams_json)
        if games_data:
            write_games_json(games_json_path, games_data)

    # LOAD
    print("Syncing new stream to the database...")
    game_cache = {game.name: game for game in context.db_session.query(Game).all()}
    
    sync_streams(context.db_session, new_streams_data, game_cache, prune_missing=False)
    if games_data:
        sync_game_stats(context.db_session, games_data, game_cache, prune_missing=False)

    # TODO: Add logic for `update_genres_for_stream`
    if update_genres_for_stream:
        print("Genre update for the new stream is not yet implemented.")

    print("Successfully synced new stream.")
