from __future__ import annotations

"""
Load layer: select/update games_meta rows for enrichment.
"""

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from database.models import Game, GameMeta
from pipeline.transform.games_meta_enrichment import GamesMetaRowView


def select_enrichment_candidates(
    session: Session,
    *,
    only_game_id: int = 0,
    limit: int = 0,
) -> list[GamesMetaRowView]:
    q = (
        session.query(GameMeta, Game)
        .join(Game, Game.id == GameMeta.game_id)
        .options(joinedload(GameMeta.game))
        .order_by(GameMeta.game_id)
    )

    if int(only_game_id) > 0:
        q = q.filter(GameMeta.game_id == int(only_game_id))
    else:
        q = q.filter(
            or_(
                GameMeta.hltb_hours.is_(None),
                GameMeta.hltb_hours <= 0,
                GameMeta.steam_url.is_(None),
                GameMeta.steam_url == "",
                GameMeta.platforms_text.is_(None),
                GameMeta.platforms_text == "",
                GameMeta.genres_text.is_(None),
                GameMeta.genres_text == "",
            )
        )

    if int(limit) > 0:
        q = q.limit(int(limit))

    out: list[GamesMetaRowView] = []
    for gm, g in q.all():
        out.append(
            GamesMetaRowView(
                game_id=int(gm.game_id),
                game_name=str(getattr(g, "name", "") or ""),
                hltb_hours=gm.hltb_hours,
                steam_url=gm.steam_url,
                platforms_text=gm.platforms_text,
                genres_text=gm.genres_text,
            )
        )
    return out


def apply_games_meta_patch(session: Session, *, game_id: int, patch: dict) -> bool:
    """
    Apply patch to GameMeta row. Commit/rollback is responsibility of caller.
    Returns True if anything changed.
    """
    if not patch:
        return False

    row = session.query(GameMeta).filter_by(game_id=int(game_id)).one_or_none()
    if row is None:
        row = GameMeta(game_id=int(game_id))
        session.add(row)
        session.flush()

    changed = False
    for k, v in patch.items():
        if getattr(row, k) != v:
            setattr(row, k, v)
            changed = True

    if changed:
        session.add(row)
    return changed


__all__ = ["apply_games_meta_patch", "select_enrichment_candidates"]

