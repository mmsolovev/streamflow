"""
Transform layer: helpers for Google Sheets values.
"""


def normalize_row(row, width: int) -> list:
    row = list(row or [])
    return row[:width] + [""] * max(0, width - len(row))


__all__ = ["normalize_row"]

