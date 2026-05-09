from __future__ import annotations



"""
Google Sheets delivery: Streams worksheet sync.
"""

from pathlib import Path

from database.db import SessionLocal
from database.models import Stream
from config.settings import SPREADSHEET_NAME, STREAMS_SHEET_NAME
from pipeline.delivery.sheets_utils import build_hyperlink_formula, get_client
from pipeline.transform.sheets_transform import normalize_row as _normalize_row


def _stream_display_date(stream: Stream) -> str:
    return stream.date.strftime("%d.%m.%Y\n%H:%M")


def _build_stream_row(stream: Stream) -> list:
    games = " -> ".join(stream_game.game.name for stream_game in stream.stream_games)
    participants = " ".join(participant.display_name for participant in stream.participants)
    vod = build_hyperlink_formula(stream.vod_url, "Twitch")
    clips = build_hyperlink_formula(stream.clips_url, "Клипы")

    return [
        _stream_display_date(stream),
        stream.duration,
        stream.title,
        games,
        vod,
        clips,
        "",
        "",
        "",
        "",
        stream.genres_text or "",
        participants,
    ]


def _format_streams_sheet(sheet, row_count: int) -> None:
    if row_count <= 0:
        return

    start_row = 9
    end_row = start_row + row_count - 1

    requests = [
        {
            "unmergeCells": {
                "range": {
                    "sheetId": sheet.id,
                    "startRowIndex": start_row - 1,
                    "endRowIndex": end_row,
                    "startColumnIndex": 5,
                    "endColumnIndex": 10,
                }
            }
        }
    ]

    for row in range(start_row, end_row + 1):
        requests.append(
            {
                "mergeCells": {
                    "range": {
                        "sheetId": sheet.id,
                        "startRowIndex": row - 1,
                        "endRowIndex": row,
                        "startColumnIndex": 5,
                        "endColumnIndex": 10,
                    },
                    "mergeType": "MERGE_ALL",
                }
            }
        )

    sheet.spreadsheet.batch_update({"requests": requests})

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

    sheet.format(
        f"A{start_row}:A{end_row}",
        {"horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE"},
    )

    sheet.format(
        f"B{start_row}:B{end_row}",
        {
            "numberFormat": {"type": "NUMBER", "pattern": "0.0"},
            "horizontalAlignment": "CENTER",
            "verticalAlignment": "MIDDLE",
        },
    )

    sheet.format(f"F{start_row}:J{end_row}", {"horizontalAlignment": "LEFT"})

    sheet.format(
        f"K{start_row}:K{end_row}",
        {
            "textFormat": {
                "fontFamily": "Montserrat",
                "fontSize": 10,
                "foregroundColor": {"red": 229 / 255, "green": 231 / 255, "blue": 235 / 255},
            }
        },
    )

    sheet.format(
        f"E{start_row}:E{end_row}",
        {
            "textFormat": {
                "fontFamily": "Orbitron",
                "fontSize": 14,
                "bold": True,
                "foregroundColor": {"red": 153 / 255, "green": 76 / 255, "blue": 255 / 255},
            },
            "horizontalAlignment": "CENTER",
            "verticalAlignment": "MIDDLE",
        },
    )


def _stream_comparable_row(row):
    normalized_row = _normalize_row(row, 12)
    return [str(value) for value in normalized_row]


def _build_stream_comparable_row(stream: Stream, manual_columns=None) -> list[str]:
    row = _build_stream_row(stream)
    comparable = [
        _stream_display_date(stream),
        str(row[1]),
        str(row[2]),
        str(row[3]),
        str(row[4]),
        str(row[5]),
        "",
        "",
        "",
        "",
        str(row[10]),
        str(row[11]),
    ]

    if manual_columns is not None:
        # G-J оставляем ручными, а K (genres_text) всегда из БД.
        comparable[6:10] = [str(value) for value in manual_columns]

    return comparable


def sync_streams() -> None:
    client = get_client()
    sheet = client.open(SPREADSHEET_NAME).worksheet(STREAMS_SHEET_NAME)

    session = SessionLocal()
    streams = session.query(Stream).order_by(Stream.date.desc()).all()
    rows = [_build_stream_row(stream) for stream in streams]
    session.close()

    sheet.batch_clear(["A9:L1000"])
    if rows:
        sheet.update("A9", rows, value_input_option="USER_ENTERED")
    _format_streams_sheet(sheet, len(rows))

    print(f"Streams synced: {len(rows)}")


def sync_streams_safe() -> None:
    client = get_client()
    sheet = client.open(SPREADSHEET_NAME).worksheet(STREAMS_SHEET_NAME)

    session = SessionLocal()

    values = sheet.get_all_values()
    data_rows = values[8:] if len(values) > 8 else []

    existing = {}
    for row in data_rows:
        normalized_row = _normalize_row(row, 12)
        key = (normalized_row[0], normalized_row[2])
        if key[0] and key[1]:
            existing[key] = normalized_row

    streams = session.query(Stream).order_by(Stream.date.desc()).all()
    final_rows = []
    comparable_final_rows = []

    for stream in streams:
        row = _build_stream_row(stream)
        row_key = (_stream_display_date(stream), stream.title)

        if row_key in existing:
            old_row = existing[row_key]
            # G-J оставляем ручными, а K (genres_text) всегда из БД.
            row[6:10] = old_row[6:10]
            comparable_row = _build_stream_comparable_row(stream, manual_columns=old_row[6:10])
        else:
            comparable_row = _build_stream_comparable_row(stream)

        final_rows.append(row)
        comparable_final_rows.append(comparable_row)

    current_rows = [_stream_comparable_row(row) for row in data_rows]

    if current_rows != comparable_final_rows:
        sheet.batch_clear(["A9:L1000"])
        if final_rows:
            _format_streams_sheet(sheet, len(final_rows))
            sheet.update("A9", final_rows, value_input_option="USER_ENTERED")
        print(f"Reordered and synced {len(final_rows)} streams")
    else:
        print("Streams already in sync")

    session.close()


__all__ = ["sync_streams", "sync_streams_safe"]
