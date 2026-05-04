from __future__ import annotations

"""
Orchestrator job: export DB state to Google Sheets.
"""

from pipeline.delivery.sheets_games import export_games_to_sheet
from pipeline.delivery.sheets_releases import export_releases_to_sheet
from pipeline.delivery.sheets_streams import export_streams_to_sheet
from .context import PipelineContext


def run(context: PipelineContext) -> None:
    """
    Exports data from the database to Google Sheets.
    """
    _ = context  # Context might be used in the future for configuration, etc.
    print("Exporting data to Google Sheets...")

    # Each function is a self-contained delivery job
    export_games_to_sheet()
    export_streams_to_sheet()
    export_releases_to_sheet()

    print("Successfully exported all data to Google Sheets.")
