from __future__ import annotations

"""
Ingest layer: fetch datasets from IGDB (upcoming games list, single-game metadata).
"""

from services.igdb_service import RecommendationMetadata, fetch_recommendation_metadata, fetch_top_upcoming_games


async def ingest_top_upcoming_games(limit: int = 15) -> list[RecommendationMetadata]:
    return await fetch_top_upcoming_games(limit=int(limit))


async def ingest_recommendation_metadata(game_name: str) -> RecommendationMetadata | None:
    return await fetch_recommendation_metadata(game_name)


__all__ = ["RecommendationMetadata", "ingest_recommendation_metadata", "ingest_top_upcoming_games"]

