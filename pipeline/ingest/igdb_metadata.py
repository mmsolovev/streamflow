from __future__ import annotations

"""
Ingest layer: fetch game metadata from IGDB.

This is a thin wrapper around `services.recommendation_metadata_service`.
"""

from services.recommendation_metadata_service import RecommendationMetadata, fetch_recommendation_metadata


async def fetch_igdb_metadata(game_name: str) -> RecommendationMetadata | None:
    return await fetch_recommendation_metadata(game_name)


__all__ = ["RecommendationMetadata", "fetch_igdb_metadata"]

