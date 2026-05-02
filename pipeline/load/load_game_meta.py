from __future__ import annotations

"""
Load layer: writes targeting `games_meta` table (GameMeta).
"""

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from database.models import Game, GameMeta
from pipeline.transform.games_transform import GamesMetaRowView
from pipeline.transform.sheets_transform import normalize_row, parse_sheet_bool


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


def _get_or_create_game_meta(game: Game) -> GameMeta:
    if not game.meta:
        game.meta = GameMeta()
    return game.meta


def apply_games_manual_fields(session: Session, rows_by_game_name: dict[str, list], width: int = 12) -> int:
    """
    Updates manual flags from Sheets targeting `games_meta`.
    Commit/rollback is responsibility of the caller.
    """
    updated = 0

    for game_name, row in (rows_by_game_name or {}).items():
        game = session.query(Game).filter_by(name=game_name).first()
        if not game:
            continue

        meta = _get_or_create_game_meta(game)
        normalized = normalize_row(row, width)

        new_liked = parse_sheet_bool(normalized[7])
        new_completed = parse_sheet_bool(normalized[9])

        # Only assign when sheet value is explicit; keep DB value otherwise.
        if new_liked is not None and bool(meta.liked) != bool(new_liked):
            meta.liked = bool(new_liked)
            updated += 1
        if new_completed is not None and bool(meta.completed) != bool(new_completed):
            meta.completed = bool(new_completed)
            updated += 1

    session.flush()
    return updated


__all__ = [
    "apply_games_manual_fields",
    "apply_games_meta_patch",
    "select_enrichment_candidates",
]

