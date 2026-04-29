from __future__ import annotations

"""
Google Sheets integration client (auth + gspread client).

Kept outside `pipeline/*` because it is an integration used by both delivery sync and ingest-from-sheets.
"""

import os

import gspread
from oauth2client.service_account import ServiceAccountCredentials


BASE_DIR = os.path.dirname(os.path.dirname(__file__))
credentials_path = os.path.join(BASE_DIR, "config", "credentials.json")


def get_client():
    scope = [
        "https://spreadsheets.google.com/feeds",
        "https://www.googleapis.com/auth/drive",
    ]

    creds = ServiceAccountCredentials.from_json_keyfile_name(credentials_path, scope)
    return gspread.authorize(creds)


__all__ = ["get_client"]

