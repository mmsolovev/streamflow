from __future__ import annotations

"""
Load layer: read/update Stream.genres_text using SQLAlchemy models.
"""

from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from database.models import Game, GameMeta, Stream, StreamGame


def iter_streams_for_genres(
    session: Session,
    *,
    only_stream_id: int = 0,
    limit: int = 0,
    force: bool = False,
) -> list[Stream]:
    q = session.query(Stream).order_by(Stream.id)

    if int(only_stream_id) > 0:
        q = q.filter(Stream.id == int(only_stream_id))
    elif not force:
        # Also filter pure-whitespace values in orchestrator to avoid sqlite trim edge cases.
        q = q.filter(or_(Stream.genres_text.is_(None), Stream.genres_text == ""))

    q = q.options(
        selectinload(Stream.stream_games).selectinload(StreamGame.game).selectinload(Game.meta),
        selectinload(Stream.participants),
    )

    if int(limit) > 0:
        q = q.limit(int(limit))

    return q.all()


def get_stream_context(stream: Stream) -> tuple[bool, list[str], list[str | None]]:
    has_participants = bool(getattr(stream, "participants", None)) and len(stream.participants) > 0

    game_names: list[str] = []
    game_genres_texts: list[str | None] = []

    for sg in list(getattr(stream, "stream_games", None) or []):
        game = getattr(sg, "game", None)
        if game is None:
            continue

        name = str(getattr(game, "name", "") or "")
        if name:
            game_names.append(name)

        meta = getattr(game, "meta", None)
        if isinstance(meta, GameMeta):
            game_genres_texts.append(getattr(meta, "genres_text", None))
        else:
            game_genres_texts.append(None)

    return has_participants, game_names, game_genres_texts


def set_stream_genres_text(session: Session, stream: Stream, genres_text: str | None) -> bool:
    """
    Mutates stream in-place. Commit/rollback is responsibility of the caller.
    Returns True if changed.
    """
    new_val = None if genres_text is None else str(genres_text)
    old_val = getattr(stream, "genres_text", None)
    if (old_val or "").strip() == (new_val or "").strip():
        return False
    stream.genres_text = new_val
    session.add(stream)
    return True


__all__ = ["get_stream_context", "iter_streams_for_genres", "set_stream_genres_text"]

