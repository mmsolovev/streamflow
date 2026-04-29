from __future__ import annotations

"""
Delivery primitives for Google Sheets.

`services.sheets_service` holds auth / client. This module holds generic upload helpers.
"""

from datetime import datetime

from services.sheets_service import get_client
from config.settings import SPREADSHEET_NAME


def format_dt(dt: datetime | None, with_time: bool = False) -> str:
    if not dt:
        return ""
    return dt.strftime("%Y-%m-%d %H:%M") if with_time else dt.strftime("%Y-%m-%d")


def upload_table(
    *,
    sheet_name: str,
    headers: list,
    rows: list,
    spreadsheet_name: str = "Tabula Streams",
):
    """
    Universal table uploader.
    - creates worksheet if missing
    - clears sheet
    - uploads headers+rows in one update
    """
    client = get_client()
    spreadsheet = client.open(spreadsheet_name)

    try:
        sheet = spreadsheet.worksheet(sheet_name)
    except Exception:
        sheet = spreadsheet.add_worksheet(title=sheet_name, rows="1000", cols="20")

    sheet.clear()
    sheet.update("A1", [headers] + rows)
    sheet.format(
        "A1:Z1",
        {"textFormat": {"bold": True, "fontSize": 11}, "horizontalAlignment": "CENTER"},
    )

    print(f"Uploaded {len(rows)} rows to '{sheet_name}'")


def get_or_create_worksheet(client, sheet_name: str, *, rows: str = "1000", cols: str = "20"):
    spreadsheet = client.open(SPREADSHEET_NAME)
    try:
        return spreadsheet.worksheet(sheet_name)
    except Exception:
        return spreadsheet.add_worksheet(title=sheet_name, rows=rows, cols=cols)


__all__ = ["format_dt", "get_client", "get_or_create_worksheet", "upload_table"]
