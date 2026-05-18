from __future__ import annotations

"""
Google Sheets delivery: Bot info worksheet sync.
"""

from pathlib import Path

from config.settings import BOT_INFO_SHEET_NAME
from pipeline.delivery.sheets_utils import get_client, get_or_create_worksheet as _get_or_create_worksheet


CHAT_COMMANDS_PATH = Path(__file__).resolve().parents[2] / "docs" / "CHAT_COMMANDS.txt"


def sync_bot_info() -> None:
    sheet = _get_or_create_worksheet(get_client(), BOT_INFO_SHEET_NAME, rows="1000", cols="12")
    text = CHAT_COMMANDS_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
    current_text = (sheet.acell("A1").value or "").replace("\r\n", "\n")

    if current_text != text:
        sheet.update("A1", [[text]], value_input_option="RAW")
        print("Bot info synced")
    else:
        print("Bot info already in sync")


__all__ = ["sync_bot_info"]
