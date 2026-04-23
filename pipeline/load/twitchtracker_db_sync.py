from __future__ import annotations

"""
Backwards-compatible facade for historical imports.

Implementation is split across `pipeline.load.twitchtracker.*` modules.
"""

from pipeline.load.twitchtracker.common import SyncStats
from pipeline.load.twitchtracker.game_stats import sync_game_stats
from pipeline.load.twitchtracker.games import get_or_create_game
from pipeline.load.twitchtracker.streams import sync_stream_games, sync_streams
from pipeline.load.update_streams_count import update_streams_count

__all__ = [
    "SyncStats",
    "get_or_create_game",
    "sync_game_stats",
    "sync_stream_games",
    "sync_streams",
    "update_streams_count",
]

