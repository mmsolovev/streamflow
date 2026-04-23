from __future__ import annotations

from sqlalchemy.orm import Session

from database.models import Game, GameMeta, Participant


def get_or_create_game(session: Session, game_cache: dict[str, Game], name: str) -> Game:
    game = game_cache.get(name)
    if game is not None:
        return game

    game = session.query(Game).filter_by(name=name).first()
    if game is None:
        game = Game(name=name)
        session.add(game)
        session.flush()

    # Many parts of the bot assume meta row exists (manual flags etc.).
    if session.query(GameMeta).filter_by(game_id=game.id).first() is None:
        game.meta = GameMeta()

    game_cache[name] = game
    return game


def get_or_create_participant(session: Session, name: str) -> Participant:
    participant = session.query(Participant).filter_by(name=name).first()
    if participant is None:
        participant = Participant(name=name, display_name=f"@{name}")
        session.add(participant)
        session.flush()
    return participant


__all__ = [
    "get_or_create_game",
    "get_or_create_participant",
]

