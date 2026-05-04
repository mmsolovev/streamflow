from __future__ import annotations

"""
Orchestrator job: parse TwitchTracker HTML pages and sync into DB.
"""

from pathlib import Path

from database.models import Game
from pipeline.delivery.json_twitchtracker import write_games_json, write_streams_json
from pipeline.ingest.twitchtracker_parser import parse_game_pages, parse_stream_pages
from pipeline.load.load_game_stats import sync_game_stats, update_streams_count
from pipeline.load.load_streams import sync_streams
from .context import PipelineContext


def run(
    context: PipelineContext,
    *,
    prune: bool = False,
    pages_dir: Path | None = None,
    write_json: bool = False,
    merge_json: bool = False,
    streams_json_path: Path | None = None,
    games_json_path: Path | None = None,
) -> None:
    """
    Args:
        context: The pipeline context.
        prune: Delete DB rows missing in the parsed dataset.
        pages_dir: Directory with TwitchTracker HTML pages. If None, uses `storage/pages`.
        write_json: Also write datasets to `storage/*.json`.
        merge_json: Merge streams.json into existing file.
        streams_json_path: Override output path for streams.json.
        games_json_path: Override output path for games.json.
    """
    if context.db_session is None:
        raise ValueError("DB session not initialized. Use `with PipelineContext(...)`.")

    # Set default paths relative to project root
    pages_dir = pages_dir if pages_dir is not None else (context.project_root / "storage" / "pages")
    streams_json_path = streams_json_path if streams_json_path is not None else (context.project_root / "storage" / "streams.json")
    games_json_path = games_json_path if games_json_path is not None else (context.project_root / "storage" / "games.json")

    # INGEST: Parse local HTML files
    print("Parsing HTML files...")
    streams_data = parse_stream_pages(pages_dir=pages_dir)
    games_data = parse_game_pages(pages_dir=pages_dir)
    print(f"Parsed {len(streams_data)} streams and {len(games_data)} games.")

    # DELIVERY (optional): Write to JSON as a backup
    if write_json:
        print("Writing to JSON files...")
        write_streams_json(streams_json_path, streams_data, merge_existing=merge_json)
        write_games_json(games_json_path, games_data)
        print(f"Wrote {streams_json_path} and {games_json_path}")

    # LOAD: Sync parsed data into the database
    print("Syncing data to the database...")
    game_cache = {game.name: game for game in context.db_session.query(Game).all()}

    stream_stats = sync_streams(context.db_session, streams_data, game_cache, prune_missing=prune)
    game_stats = sync_game_stats(context.db_session, games_data, game_cache, prune_missing=prune)
    streams_count_updated = update_streams_count(context.db_session)

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
