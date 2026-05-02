from __future__ import annotations

"""
Google Sheets delivery: Recommendations worksheet sync (released games list).
"""

from database.db import SessionLocal
from database.models import RecommendedGame
from config.settings import RECOMMENDATIONS_SHEET_NAME
from pipeline.delivery.sheets_utils import (
    build_hyperlink_formula,
    build_recommenders_text,
    build_tags_text,
    comparable_row,
    format_rating_value,
    get_client,
    get_or_create_worksheet as _get_or_create_worksheet,
)
from services.recommendations_service import STATUS_RELEASED, refresh_recommendation_lifecycle


def _format_recommendations_sheet(sheet, row_count):
    if row_count <= 0:
        return

    start_row = 9
    end_row = start_row + row_count - 1

    sheet.format(
        f"A{start_row}:I{end_row}",
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

    sheet.format(
        f"B{start_row}:B{end_row}",
        {
            "numberFormat": {"type": "NUMBER", "pattern": "0"},
            "horizontalAlignment": "CENTER",
            "verticalAlignment": "MIDDLE",
        },
    )


def _build_recommendation_row(recommendation):
    steam = build_hyperlink_formula(recommendation.steam_url)
    return [
        recommendation.release_date.strftime("%d.%m.%Y") if recommendation.release_date else "",
        len(recommendation.votes),
        recommendation.title,
        steam,
        format_rating_value(recommendation),
        build_tags_text(recommendation),
        "",
        "",
        build_recommenders_text(recommendation),
    ]


def sync_recommendations_safe() -> None:
    refresh_recommendation_lifecycle()

    client = get_client()
    sheet = _get_or_create_worksheet(client, RECOMMENDATIONS_SHEET_NAME)

    session = SessionLocal()
    values = sheet.get_all_values()
    data_rows = values[8:] if len(values) > 8 else []

    recommendations = (
        session.query(RecommendedGame)
        .filter(RecommendedGame.status == STATUS_RELEASED, RecommendedGame.release_date.is_not(None))
        .order_by(RecommendedGame.release_date.asc(), RecommendedGame.title.asc())
        .all()
    )
    rows = [_build_recommendation_row(recommendation) for recommendation in recommendations]

    current_rows = [comparable_row(row, 9) for row in data_rows]
    comparable_final_rows = [comparable_row(row, 9) for row in rows]

    if current_rows != comparable_final_rows:
        sheet.batch_clear(["A9:I1000"])
        if rows:
            _format_recommendations_sheet(sheet, len(rows))
            sheet.update("A9", rows, value_input_option="USER_ENTERED")
        print(f"Recommendations synced: {len(rows)}")
    else:
        print("Recommendations already in sync")

    session.close()


__all__ = ["sync_recommendations_safe"]
