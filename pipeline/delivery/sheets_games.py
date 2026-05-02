from __future__ import annotations

"""
Google Sheets delivery: Games worksheet sync.
"""

from database.db import SessionLocal
from database.models import Game, GameMeta, GameStats
from config.settings import SPREADSHEET_NAME, GAMES_SHEET_NAME
from pipeline.delivery.sheets_utils import build_hyperlink_formula, build_tags_text, comparable_row, format_dt, get_client
from pipeline.transform.sheets_transform import normalize_row as _normalize_row


def _get_game_meta(game: Game) -> GameMeta:
    # Delivery code must not create DB rows as a side-effect of exporting data.
    return game.meta or GameMeta()


def _build_games_dataset(session):
    ranked_games_data = []

    for game in session.query(Game).all():
        stats = (
            session.query(GameStats)
            .filter_by(
                game_id=game.id,
                period="all",
            )
            .first()
        )
        if stats:
            ranked_games_data.append((game, stats))

    ranked_games_data.sort(key=lambda item: (-(item[1].hours_streamed or 0), item[0].name.casefold()))

    ranked_rows = []
    for rank, (game, stats) in enumerate(ranked_games_data, start=1):
        ranked_rows.append((game, stats, rank))

    ranked_rows.sort(
        key=lambda item: (
            item[1].last_stream is None,
            -(item[1].last_stream.timestamp()) if item[1].last_stream else 0,
            item[0].name.casefold(),
        )
    )

    return ranked_rows


def _build_game_row(game, stats, rank, manual_columns=None):
    meta = _get_game_meta(game)
    steam = build_hyperlink_formula(meta.steam_url)

    row = [
        format_dt(stats.last_stream) if stats.last_stream else "",
        int(stats.streams_count or 0),
        game.name,
        rank,
        stats.hours_streamed or 0,
        meta.hltb_hours if meta.hltb_hours else "",
        steam,
        bool(meta.liked),
        '=IF(HROW()=TRUE;"❤";"")',
        bool(meta.completed),
        '=IF(JROW()=TRUE;"✅";"")',
        build_tags_text(meta),
    ]

    if manual_columns is not None:
        row[8] = manual_columns[0]
        row[10] = manual_columns[2]

    return row


def _finalize_game_row_formulas(rows, start_row=9):
    for offset, row in enumerate(rows):
        sheet_row = start_row + offset
        row[8] = f'=IF(H{sheet_row}=TRUE;"❤";"")'
        row[10] = f'=IF(J{sheet_row}=TRUE;"✅";"")'
    return rows


def _format_games_sheet(sheet, row_count):
    if row_count <= 0:
        return

    start_row = 9
    end_row = start_row + row_count - 1

    sheet.format(
        f"A{start_row}:L{end_row}",
        {
            "wrapStrategy": "WRAP",
            "verticalAlignment": "MIDDLE",
            "textFormat": {
                "fontFamily": "Montserrat",
                "fontSize": 14,
                "foregroundColor": {"red": 229 / 255, "green": 231 / 255, "blue": 235 / 255},
            },
        },
    )

    sheet.format(f"A{start_row}:E{end_row}", {"horizontalAlignment": "CENTER"})

    requests = []
    for column_index in (7, 9):
        requests.append(
            {
                "setDataValidation": {
                    "range": {
                        "sheetId": sheet.id,
                        "startRowIndex": start_row - 1,
                        "endRowIndex": end_row,
                        "startColumnIndex": column_index,
                        "endColumnIndex": column_index + 1,
                    },
                    "rule": {
                        "condition": {"type": "BOOLEAN"},
                        "showCustomUi": True,
                        "strict": True,
                    },
                }
            }
        )

    sheet.spreadsheet.batch_update({"requests": requests})

    sheet.format(
        f"L{start_row}:L{end_row}",
        {
            "textFormat": {
                "fontFamily": "Montserrat",
                "fontSize": 10,
                "foregroundColor": {"red": 229 / 255, "green": 231 / 255, "blue": 235 / 255},
            }
        },
    )

    sheet.format(
        f"G{start_row}:G{end_row}",
        {
            "textFormat": {
                "fontFamily": "Orbitron",
                "fontSize": 14,
                "bold": True,
                "foregroundColor": {"red": 102 / 255, "green": 192 / 255, "blue": 244 / 255},
            },
            "horizontalAlignment": "CENTER",
            "verticalAlignment": "MIDDLE",
        },
    )


def _game_comparable_row(row):
    return comparable_row(_normalize_row(row, 12), 12)


def sync_games() -> None:
    client = get_client()
    sheet = client.open(SPREADSHEET_NAME).worksheet(GAMES_SHEET_NAME)

    session = SessionLocal()
    rows = []
    for game, stats, rank in _build_games_dataset(session):
        rows.append(_build_game_row(game, stats, rank))
    _finalize_game_row_formulas(rows)
    session.close()

    sheet.batch_clear(["A9:L1000"])
    if rows:
        sheet.update("A9", rows, value_input_option="USER_ENTERED")
        _format_games_sheet(sheet, len(rows))

    print(f"Games synced: {len(rows)}")


def sync_games_safe() -> None:
    client = get_client()
    sheet = client.open(SPREADSHEET_NAME).worksheet(GAMES_SHEET_NAME)

    session = SessionLocal()

    values = sheet.get_all_values()
    data_rows = values[8:] if len(values) > 8 else []

    final_rows = []
    for game, stats, rank in _build_games_dataset(session):
        final_rows.append(_build_game_row(game, stats, rank))
    _finalize_game_row_formulas(final_rows)

    current_rows = [_game_comparable_row(row) for row in data_rows]
    comparable_final_rows = [_game_comparable_row(row) for row in final_rows]

    if current_rows != comparable_final_rows:
        sheet.batch_clear(["A9:L1000"])
        if final_rows:
            _format_games_sheet(sheet, len(final_rows))
            sheet.update("A9", final_rows, value_input_option="USER_ENTERED")
        print(f"Reordered and synced {len(final_rows)} games")
    else:
        print("Games already in sync")

    session.close()


__all__ = ["sync_games", "sync_games_safe"]
