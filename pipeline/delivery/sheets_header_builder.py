from __future__ import annotations

"""
Delivery helper: build/format the decorative header area in the Google Sheets UI.

This contains layout/formatting calls only (no DB).
"""


def set_row_heights(sheet, start, end, height):
    requests = [
        {
            "updateDimensionProperties": {
                "range": {
                    "sheetId": sheet.id,
                    "dimension": "ROWS",
                    "startIndex": start - 1,
                    "endIndex": end,
                },
                "properties": {"pixelSize": height},
                "fields": "pixelSize",
            }
        }
    ]
    sheet.spreadsheet.batch_update({"requests": requests})


def set_column_widths(sheet, widths):
    """
    widths: list of (start_col, end_col, width_px)
    """
    requests = []
    for start, end, width in widths:
        requests.append(
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": sheet.id,
                        "dimension": "COLUMNS",
                        "startIndex": start - 1,
                        "endIndex": end,
                    },
                    "properties": {"pixelSize": width},
                    "fields": "pixelSize",
                }
            }
        )

    sheet.spreadsheet.batch_update({"requests": requests})


def build_header(sheet):
    # 1) Clear
    sheet.batch_clear(["A1:N8"])

    # 2) Merge layout
    sheet.merge_cells("A1:C7")  # photo
    sheet.merge_cells("D1:J4")  # nickname
    sheet.merge_cells("D5:J6")  # description
    sheet.merge_cells("K1:N7")  # socials

    # 3) Content
    sheet.update("D1", [["Tabula"]])
    sheet.update("D5", [["Архив стримов и игр 💜"]])

    socials = [
        "🟣 Twitch",
        "📣 Telegram",
        "▶️ YouTube",
        "💰 Boosty",
        "💬 Discord",
    ]
    for i, text in enumerate(socials, start=1):
        sheet.update(f"K{i}", [[text]])

    # 4) Styles
    sheet.format(
        "A1:N7",
        {
            "backgroundColor": {"red": 0.16, "green": 0.16, "blue": 0.16},
        },
    )

    sheet.format(
        "D1:J4",
        {
            "textFormat": {
                "bold": True,
                "fontSize": 32,
                "foregroundColor": {"red": 0.6, "green": 0.3, "blue": 1.0},
            },
            "horizontalAlignment": "LEFT",
            "verticalAlignment": "BOTTOM",
        },
    )

    sheet.format(
        "D5:J6",
        {
            "textFormat": {
                "fontSize": 12,
                "foregroundColor": {"red": 0.8, "green": 0.8, "blue": 0.8},
            },
            "horizontalAlignment": "LEFT",
            "verticalAlignment": "TOP",
        },
    )

    sheet.format(
        "K1:N7",
        {
            "textFormat": {"fontSize": 12, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
            "horizontalAlignment": "LEFT",
            "verticalAlignment": "MIDDLE",
        },
    )

    # 5) Remove inner borders
    sheet.format(
        "A1:N7",
        {
            "borders": {
                "top": {"style": "NONE"},
                "bottom": {"style": "NONE"},
                "left": {"style": "NONE"},
                "right": {"style": "NONE"},
            }
        },
    )

    # 6) Outer border
    sheet.format(
        "A1:N7",
        {
            "borders": {
                "top": {"style": "SOLID", "width": 3, "color": {"red": 0.6, "green": 0.3, "blue": 1.0}},
                "bottom": {"style": "SOLID", "width": 3, "color": {"red": 0.6, "green": 0.3, "blue": 1.0}},
                "left": {"style": "SOLID", "width": 3, "color": {"red": 0.6, "green": 0.3, "blue": 1.0}},
                "right": {"style": "SOLID", "width": 3, "color": {"red": 0.6, "green": 0.3, "blue": 1.0}},
            }
        },
    )

    # 7) Column sizes
    set_column_widths(
        sheet,
        [
            (1, 3, 140),
            (4, 10, 110),
            (11, 14, 140),
        ],
    )

    # 8) Row sizes
    sheet.resize(rows=1000)
    set_row_heights(sheet, 1, 7, 40)

    # 9) Freeze
    sheet.freeze(rows=7)

    print("Header rebuilt")


__all__ = ["build_header", "set_column_widths", "set_row_heights"]

