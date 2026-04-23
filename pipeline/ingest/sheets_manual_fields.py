"""
Pipeline ingest layer: считывание отредактированных пользователем полей «вручную» из Google Sheets.

"""

from services.google_sheets_service import get_client

from pipeline.sheets import (
    GAMES_SHEET_NAME,
    RELEASES_SHEET_NAME,
    SPREADSHEET_NAME,
    get_or_create_worksheet,
)
from pipeline.transform.sheets_values import normalize_row


def ingest_games_manual_rows(width: int = 12, header_rows: int = 8) -> dict[str, list]:
    """
    Returns: {game_name: normalized_row}
    """
    client = get_client()
    sheet = client.open(SPREADSHEET_NAME).worksheet(GAMES_SHEET_NAME)

    values = sheet.get_all_values()
    data_rows = values[header_rows:] if len(values) > header_rows else []

    existing: dict[str, list] = {}
    for row in data_rows:
        normalized = normalize_row(row, width)
        game_name = normalized[2]
        if game_name:
            existing[game_name] = normalized
    return existing


def ingest_releases_manual_rows(width: int = 12, header_rows: int = 8) -> dict[str, list]:
    """
    Returns: {title: normalized_row}
    """
    client = get_client()
    sheet = get_or_create_worksheet(client, RELEASES_SHEET_NAME)

    values = sheet.get_all_values()
    data_rows = values[header_rows:] if len(values) > header_rows else []

    existing: dict[str, list] = {}
    for row in data_rows:
        normalized = normalize_row(row, width)
        title = normalized[2]
        if title:
            existing[title] = normalized
    return existing
