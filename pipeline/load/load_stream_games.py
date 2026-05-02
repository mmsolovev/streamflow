from __future__ import annotations

"""
Load layer: writes targeting `stream_games` association table (StreamGame).
"""

from sqlalchemy.orm import Session

from database.models import Game, Stream, StreamGame
from pipeline.load.load_games import get_or_create_game


def unique_in_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        if v in seen:
            continue
        seen.add(v)
        out.append(v)
    return out


def sync_stream_games(session: Session, stream: Stream, game_names: list[str], game_cache: dict[str, Game]) -> bool:
    """
    Ensures Stream.stream_games match the given ordered list of names.
    Returns True if association changed.
    """
    desired_names = unique_in_order([n for n in game_names if n])
    desired_set = set(desired_names)
    changed = False

    existing_by_name = {sg.game.name: sg for sg in stream.stream_games}

    # Remove missing.
    for game_name, stream_game in list(existing_by_name.items()):
        if game_name not in desired_set:
            stream.stream_games.remove(stream_game)
            changed = True

    # Rebuild map after removals.
    existing_by_name = {sg.game.name: sg for sg in stream.stream_games}

    # Upsert with correct positions.
    for position, game_name in enumerate(desired_names):
        game = get_or_create_game(session, game_cache, game_name)
        stream_game = existing_by_name.get(game_name)
        if stream_game is None:
            stream.stream_games.append(StreamGame(game=game, position=position))
            changed = True
        elif stream_game.position != position:
            stream_game.position = position
            changed = True

    return changed


__all__ = ["sync_stream_games", "unique_in_order"]

