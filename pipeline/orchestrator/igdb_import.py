from __future__ import annotations

"""
Orchestrator job: import upcoming games from IGDB.
"""

from pipeline.ingest.igdb_upcoming import ingest_top_upcoming_games
from pipeline.load.load_recommendations import sync_recommendations
from .context import PipelineContext


async def run(context: PipelineContext, limit: int = 15) -> None:
    """
    Fetches top upcoming games from IGDB and syncs them to the RecommendedGame table.
    """
    if context.db_session is None:
        raise ValueError("DB session not initialized. Use `with PipelineContext(...)`.")

    print(f"Fetching top {limit} upcoming games from IGDB...")
    upcoming_games = await ingest_top_upcoming_games(limit=limit)
    print(f"Fetched {len(upcoming_games)} games.")

    if not upcoming_games:
        return

    print("Syncing recommendations to the database...")
    stats = sync_recommendations(context.db_session, upcoming_games)
    print(
        f"Recommendations -> added: {stats.added}, "
        f"updated: {stats.updated}, "
f"unchanged: {stats.unchanged}"
    )
