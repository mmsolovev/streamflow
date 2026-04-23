"""
Runtime job: import user-edited manual fields from Google Sheets into the DB.

This is the ingest -> transform -> load direction for Sheets, separate from
delivery exports (DB -> Sheets).
"""

from database.db import SessionLocal
from pipeline.ingest.sheets_manual_fields import ingest_games_manual_rows, ingest_releases_manual_rows
from pipeline.load.sheets_manual_fields import apply_games_manual_fields, apply_releases_manual_fields


def import_all_manual_fields() -> None:
    games_rows = ingest_games_manual_rows()
    releases_rows = ingest_releases_manual_rows()

    session = SessionLocal()
    try:
        updated_games = apply_games_manual_fields(session, games_rows)
        updated_releases = apply_releases_manual_fields(session, releases_rows)
        session.commit()
    finally:
        session.close()

    print(f"Manual fields imported. Game fields updated: {updated_games}. Release fields updated: {updated_releases}.")


def main() -> None:
    import_all_manual_fields()


if __name__ == "__main__":
    main()

