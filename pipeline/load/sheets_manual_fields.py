"""
Pipeline load layer: apply user-edited fields from Sheets into the DB.

This is intentionally separate from delivery exports (DB -> Sheets) to keep the
pipeline directions explicit.
"""

from database.models import Game, GameMeta, RecommendedGame
from pipeline.transform.sheets_values import normalize_row, parse_sheet_bool


def _get_or_create_game_meta(game: Game) -> GameMeta:
    if not game.meta:
        game.meta = GameMeta()
    return game.meta


def apply_games_manual_fields(session, rows_by_game_name: dict[str, list], width: int = 12) -> int:
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


def apply_releases_manual_fields(session, rows_by_title: dict[str, list], width: int = 12) -> int:
    updated = 0

    for title, row in (rows_by_title or {}).items():
        recommendation = session.query(RecommendedGame).filter_by(title=title).first()
        if not recommendation:
            continue

        normalized = normalize_row(row, width)
        sheet_value = parse_sheet_bool(normalized[5])

        # Preserve previous semantics from legacy sync:
        # - TRUE always sets streamer_interested=True
        # - FALSE does not override True once it's set
        if sheet_value is True and recommendation.streamer_interested is not True:
            recommendation.streamer_interested = True
            updated += 1
        elif sheet_value is False and recommendation.streamer_interested is False:
            recommendation.streamer_interested = False

    session.flush()
    return updated

