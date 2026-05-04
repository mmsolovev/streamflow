from __future__ import annotations

"""
Orchestrator job: fill short descriptions for RecommendedGame rows using AI.
"""

import asyncio

from sqlalchemy import and_

from database.models import RecommendedGame
from pipeline.transform.recommended_game_descriptions import generate_short_description
from .context import PipelineContext


async def run(context: PipelineContext, limit: int = 10) -> None:
    """
    Finds recommended games without a short description and generates it using an AI model.

    Args:
        context: The pipeline context.
        limit: The maximum number of descriptions to generate in one run.
    """
    if context.db_session is None:
        raise ValueError("DB session not initialized. Use `with PipelineContext(...)`.")

    # LOAD (from DB): Find games that need a description
    games_to_enrich = (
        context.db_session.query(RecommendedGame)
        .filter(
            and_(
                RecommendedGame.short_description.is_(None),
                RecommendedGame.summary.is_not(None),
            )
        )
        .limit(limit)
        .all()
    )

    if not games_to_enrich:
        print("No games found that need a description. Nothing to do.")
        return

    print(f"Found {len(games_to_enrich)} games to enrich with descriptions.")

    # TRANSFORM & LOAD: Generate descriptions and update DB
    tasks = []
    for game in games_to_enrich:
        tasks.append(_enrich_game(game))

    results = await asyncio.gather(*tasks)
    updated_count = sum(1 for r in results if r is True)

    print(f"Successfully generated and saved descriptions for {updated_count} games.")


async def _enrich_game(game: RecommendedGame) -> bool:
    """Helper to process a single game."""
    if not game.summary:
        return False

    print(f"Generating description for '{game.title}'...")
    description = await generate_short_description(game.summary)

    if description:
        game.short_description = description
        print(f"  -> Success: '{description[:50]}...'")
        return True
    else:
        print(f"  -> Failed to generate description for '{game.title}'.")
        return False
