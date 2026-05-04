from __future__ import annotations

"""
Orchestrator job: enrich games_meta in SQLite.
"""

import asyncio

from sqlalchemy import or_

from database.models import Game
from pipeline.ingest.hltb import search_best as search_hltb
from pipeline.ingest.igdb_metadata import fetch_igdb_metadata
from pipeline.transform.games_meta_enrichment import GamesMetaRowView, IgdbMetaView, build_patch
from pipeline.transform.igdb_transform import join_names, build_platforms_text, extract_steam_url
from .context import PipelineContext


async def run(
    context: PipelineContext,
    *,
    limit: int = 25,
    force: bool = False,
    only_game_id: int = 0,
) -> None:
    """
    Enriches game metadata (HLTB, IGDB) and saves it to the database.

    Args:
        context: The pipeline context.
        limit: Max games to process.
        force: Re-enrich even if data is already present.
        only_game_id: Process only this game ID.
    """
    if context.db_session is None:
        raise ValueError("DB session not initialized. Use `with PipelineContext(...)`.")

    query = context.db_session.query(Game)
    if only_game_id:
        query = query.filter(Game.id == only_game_id)
    elif not force:
        query = query.filter(
            or_(
                Game.hltb_hours.is_(None),
                Game.steam_url.is_(None),
                Game.platforms_text.is_(None),
                Game.genres_text.is_(None),
            )
        )

    games_to_process = query.order_by(Game.id.desc()).limit(limit).all()

    if not games_to_process:
        print("No games to enrich. Nothing to do.")
        return

    print(f"Found {len(games_to_process)} games to enrich.")

    tasks = [_enrich_game(context, game) for game in games_to_process]
    await asyncio.gather(*tasks)

    print("Enrichment process finished.")


async def _enrich_game(context: PipelineContext, game: Game) -> None:
    """Helper to process a single game."""
    print(f"Enriching '{game.name}' (ID: {game.id})...")

    # Fetch data from external services
    hltb_result = await asyncio.to_thread(search_hltb, game.name, min_similarity=0.8)
    igdb_result = await fetch_igdb_metadata(game.name)

    # Transform data
    igdb_view = None
    if igdb_result:
        igdb_view = IgdbMetaView(
            steam_url=extract_steam_url(igdb_result.get("websites")),
            platforms_text=build_platforms_text(igdb_result.get("platforms")),
            genres_text=join_names(igdb_result.get("genres")),
        )

    row_view = GamesMetaRowView(
        game_id=game.id,
        game_name=game.name,
        hltb_hours=game.hltb_hours,
        steam_url=game.steam_url,
        platforms_text=game.platforms_text,
        genres_text=game.genres_text,
    )

    patch = build_patch(
        row=row_view,
        hltb_hours=hltb_result.hltb_hours if hltb_result else None,
        igdb=igdb_view,
    )

    if not patch:
        print(f"  -> No new data found for '{game.name}'.")
        return

    # Load data
    print(f"  -> Found new data: {list(patch.keys())}")
    for key, value in patch.items():
        setattr(game, key, value)
