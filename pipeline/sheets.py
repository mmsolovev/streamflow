"""
Shared Google Sheets configuration + small helpers.

Used by pipeline ingest/delivery/runtime jobs.
"""


SPREADSHEET_NAME = "Tabula Streams"

STREAMS_SHEET_NAME = "СТРИМЫ"
GAMES_SHEET_NAME = "ИГРЫ"
BOT_INFO_SHEET_NAME = "БОТ"

RELEASES_SHEET_NAME = "РЕЛИЗЫ"
RECOMMENDATIONS_SHEET_NAME = "СОВЕТЫ"


def get_or_create_worksheet(client, sheet_name: str, rows: str = "1000", cols: str = "20"):
    spreadsheet = client.open(SPREADSHEET_NAME)
    try:
        return spreadsheet.worksheet(sheet_name)
    except Exception:
        return spreadsheet.add_worksheet(title=sheet_name, rows=rows, cols=cols)

