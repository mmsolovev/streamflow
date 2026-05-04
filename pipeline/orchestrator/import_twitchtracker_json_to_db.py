from __future__ import annotations

"""
Orchestrator job: import TwitchTracker JSON files into DB.
"""

from pathlib import Path

from database.models import Game
from pipeline.ingest.twitchtracker_parser import load_games_json, load_streams_json
from pipeline.load.load_game_stats import sync_game_stats, update_streams_count
from pipeline.load.load_streams import sync_streams
from pipeline.transform.stream_genres import compute_stream_genres
from .context import PipelineContext


def run(
    context: PipelineContext,
    *,
    streams_path: Path | None = None,
    games_path: Path | None = None,
    prune: bool = True,
    sync_participants_from_title: bool = True,
) -> None:
    """
    Args:
        context: The pipeline context.
        streams_path: Path to streams.json. If None, uses `storage/streams.json`.
        games_path: Path to games.json. If None, uses `storage/games.json`.
        prune: Delete DB rows missing in the parsed dataset.
        sync_participants_from_title: Sync participants from @mentions in stream titles.
    """
    if context.db_session is None:
        raise ValueError("DB session not initialized. Use `with PipelineContext(...)`.")

    # Set default paths relative to project root
    streams_path = streams_path if streams_path is not None else (context.project_root / "storage" / "streams.json")
    games_path = games_path if games_path is not None else (context.project_root / "storage" / "games.json")

    # INGEST: Load from JSON files
    print("Loading from JSON files...")
    streams_data = load_streams_json(streams_path)
    games_data = load_games_json(games_path)
    print(f"Loaded {len(streams_data)} streams and {len(games_data)} games.")

    # LOAD: Sync data into the database
    print("Syncing data to the database...")
    game_cache = {game.name: game for game in context.db_session.query(Game).all()}

    stream_stats = sync_streams(
        context.db_session,
        streams_data,
        game_cache,
        prune_missing=prune,
        sync_participants_from_title=sync_participants_from_title,
    )
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
