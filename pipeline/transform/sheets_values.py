"""
Вспомогательные функции преобразования данных для значений Google Sheets.

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

