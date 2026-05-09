from __future__ import annotations

"""
Google Sheets delivery: Releases worksheet sync (upcoming + unknown release date).
"""

from datetime import datetime

from database.db import SessionLocal
from database.models import RecommendedGame
from config.settings import RELEASES_SHEET_NAME
from pipeline.delivery.sheets_utils import (
    build_hyperlink_formula,
    build_recommenders_text,
    build_tags_text,
    comparable_row,
    get_client,
    get_or_create_worksheet as _get_or_create_worksheet,
)
from pipeline.transform.sheets_transform import normalize_row as _normalize_row, parse_sheet_bool
from services.recommendations_service import STATUS_UPCOMING, refresh_recommendation_lifecycle


def _format_releases_sheet(sheet, row_count):
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
                    "startColumnIndex": 6,
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
                        "startColumnIndex": 6,
                        "endColumnIndex": 10,
                    },
                    "mergeType": "MERGE_ALL",
                }
            }
        )
        requests.append(
            {
                "setDataValidation": {
                    "range": {
                        "sheetId": sheet.id,
                        "startRowIndex": row - 1,
                        "endRowIndex": row,
                        "startColumnIndex": 5,
                        "endColumnIndex": 6,
                    },
                    "rule": {
                        "condition": {"type": "BOOLEAN"},
                        "showCustomUi": True,
                        "strict": True,
                    },
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
        f"A{start_row}:B{end_row}",
        {"horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE"},
    )


def _format_release_value(recommendation):
    if not recommendation.release_date:
        return ""
    return recommendation.release_date.strftime("%d.%m.%Y\n%H:%M")


def _format_release_delta(recommendation):
    if not recommendation.release_date:
        return ""

    today = datetime.utcnow().date()
    release_day = recommendation.release_date.date()
    days = (release_day - today).days

    if days < 0:
        return ""
    if days == 0:
        return "сегодня"
    return f"{days} д."


def _sync_release_manual_fields_from_sheet(session, existing_rows):
    for recommendation_name, row in existing_rows.items():
        recommendation = session.query(RecommendedGame).filter_by(title=recommendation_name).first()
        if not recommendation:
            continue

        normalized_row = _normalize_row(row, 12)
        sheet_value = parse_sheet_bool(normalized_row[5])
        if sheet_value is True:
            recommendation.streamer_interested = True
        elif sheet_value is False and recommendation.streamer_interested is False:
            recommendation.streamer_interested = False

    session.flush()


def _release_comparable_row(row):
    normalized_row = _normalize_row(row, 12)
    comparable = []
    for value in normalized_row:
        if value is True:
            comparable.append("TRUE")
        elif value is False:
            comparable.append("FALSE")
        else:
            comparable.append(str(value))
    return comparable


def _build_release_row(recommendation):
    steam = build_hyperlink_formula(recommendation.steam_url)
    return [
        _format_release_value(recommendation),
        _format_release_delta(recommendation),
        recommendation.title,
        recommendation.description_short or "",
        steam,
        bool(recommendation.streamer_interested),
        "",
        "",
        "",
        "",
        build_tags_text(recommendation),
        build_recommenders_text(recommendation),
    ]


def sync_releases_safe() -> None:
    refresh_recommendation_lifecycle()

    client = get_client()
    sheet = _get_or_create_worksheet(client, RELEASES_SHEET_NAME)

    session = SessionLocal()
    values = sheet.get_all_values()
    data_rows = values[8:] if len(values) > 8 else []

    existing = {}
    for row in data_rows:
        normalized_row = _normalize_row(row, 12)
        title = normalized_row[2]
        if title:
            existing[title] = normalized_row

    _sync_release_manual_fields_from_sheet(session, existing)

    recommendations = (
        session.query(RecommendedGame)
        .filter((RecommendedGame.status == STATUS_UPCOMING) | (RecommendedGame.release_date.is_(None)))
        .order_by(
            RecommendedGame.release_date.is_(None),
            RecommendedGame.release_date.asc(),
            RecommendedGame.title.asc(),
        )
        .all()
    )

    rows = []
    for offset, recommendation in enumerate(recommendations, start=9):
        row = _build_release_row(recommendation)
        row[6] = f'=IF(F{offset}=TRUE;"👍";"")'
        rows.append(row)

    current_rows = [_release_comparable_row(row) for row in data_rows]
    comparable_final_rows = [_release_comparable_row(row) for row in rows]

    if current_rows != comparable_final_rows:
        sheet.batch_clear(["A9:L1000"])
        if rows:
            _format_releases_sheet(sheet, len(rows))
            sheet.update("A9", rows, value_input_option="USER_ENTERED")

    print(f"Releases synced: {len(rows)}")

    session.commit()
    session.close()


__all__ = ["sync_releases_safe"]
