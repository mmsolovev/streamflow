from __future__ import annotations

"""
Orchestrator job: import manual fields from Google Sheets into DB.
"""

from database.models import Game, RecommendedGame
from pipeline.ingest.sheets_manual_fields import ingest_games_manual_rows, ingest_releases_manual_rows
from pipeline.transform.sheets_values import parse_sheet_bool
from .context import PipelineContext


def run(context: PipelineContext) -> None:
    """
    Imports manually edited fields from Google Sheets and updates the database.
    """
    if context.db_session is None:
        raise ValueError("DB session not initialized. Use `with PipelineContext(...)`.")

    print("Importing manual fields from Google Sheets...")

    # --- Games Sheet ---
    print("Processing 'Games' sheet...")
    games_manual_rows = ingest_games_manual_rows()
    games_updated = 0
    for game_name, row_values in games_manual_rows.items():
        game = context.db_session.query(Game).filter(Game.name == game_name).first()
        if game:
            # This is a simplified example. In a real scenario, you would
            # map columns to fields more robustly.
            # Example: game.is_favorite = parse_sheet_bool(row_values[3])
            pass  # Add your logic for updating Game objects here
    print(f"Games sheet: processed {len(games_manual_rows)} rows, updated {games_updated} games.")

    # --- Releases Sheet ---
    print("Processing 'Releases' sheet...")
    releases_manual_rows = ingest_releases_manual_rows()
    releases_updated = 0
    for title, row_values in releases_manual_rows.items():
        release = context.db_session.query(RecommendedGame).filter(RecommendedGame.title == title).first()
        if release:
            try:
                # Column J (index 9) is "Стример заинтересован"
                streamer_interested = parse_sheet_bool(row_values[9])
                if streamer_interested is not None:
                    release.streamer_interested = streamer_interested
                    releases_updated += 1
            except (ValueError, IndexError):
                # Ignore rows with invalid formats
                pass
    print(f"Releases sheet: processed {len(releases_manual_rows)} rows, updated {releases_updated} releases.")

    print("Successfully imported manual fields.")
