"""
Pipeline transform helpers for Google Sheets values.

Keep these in transform (not delivery) so both ingest->load jobs and delivery jobs
can share normalization/parsing without mixing responsibilities.
"""


def normalize_row(row, width: int) -> list:
    row = list(row or [])
    return row[:width] + [""] * max(0, width - len(row))


def parse_sheet_bool(value):
    normalized = str(value).strip().upper()
    if normalized in {"TRUE", "ИСТИНА"}:
        return True
    if normalized in {"FALSE", "ЛОЖЬ"}:
        return False
    return None

