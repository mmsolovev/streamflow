from __future__ import annotations

"""
Orchestrator job: compute streams.genres_text.
"""

from database.models import Game, GameStat, Stream
from pipeline.transform.stream_genres import compute_stream_genres
from .context import PipelineContext


def run(
    context: PipelineContext,
    *,
    limit: int = 0,
    only_stream_id: int = 0,
    force: bool = False,
) -> None:
    """
    Computes and updates the `genres_text` for streams.

    Args:
        context: The pipeline context.
        limit: Max streams to process (0 = no limit).
        only_stream_id: Process only this stream id.
        force: Recompute even if `genres_text` is not blank.
    """
    if context.db_session is None:
        raise ValueError("DB session not initialized. Use `with PipelineContext(...)`.")

    query = context.db_session.query(Stream)
    if only_stream_id:
        query = query.filter(Stream.id == only_stream_id)
    elif not force:
        query = query.filter(Stream.genres_text.is_(None))

    if limit > 0:
        query = query.limit(limit)

    streams_to_process = query.all()
    if not streams_to_process:
        print("No streams to process. Nothing to do.")
        return

    print(f"Found {len(streams_to_process)} streams to enrich with genres.")

    # Eager load related data
    game_ids = {game.game_id for stream in streams_to_process for game in stream.games}
    games_meta = {g.id: g for g in context.db_session.query(Game).filter(Game.id.in_(game_ids))}
    game_stats = {gs.name: gs for gs in context.db_session.query(GameStat).filter(GameStat.name.in_([g.name for g in games_meta.values()]))}

    updated_count = 0
    for stream in streams_to_process:
        game_names = [games_meta[g.game_id].name for g in stream.games if g.game_id in games_meta]
        game_genres_texts = [
            game_stats[name].genres_text for name in game_names if name in game_stats and game_stats[name].genres_text
        ]

        genres_text = compute_stream_genres(
            title=stream.title,
            has_participants=bool(stream.participants),
            game_names=game_names,
            game_genres_texts=game_genres_texts,
        )

        if genres_text != stream.genres_text:
            stream.genres_text = genres_text
            updated_count += 1

    print(f"Successfully updated genres for {updated_count} streams.")
