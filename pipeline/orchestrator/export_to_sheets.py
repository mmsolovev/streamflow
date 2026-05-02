"""
Orchestrator job: export data to Google Sheets UI.

Implementation lives in pipeline.delivery.*; this file is the stable pipeline entrypoint.
"""

from pipeline.delivery.sheets_bot_info import sync_bot_info
from pipeline.delivery.sheets_games import sync_games_safe
from pipeline.delivery.sheets_recommendations import sync_recommendations_safe
from pipeline.delivery.sheets_releases import sync_releases_safe
from pipeline.delivery.sheets_streams import sync_streams_safe


def export_all() -> None:
    sync_bot_info()
    sync_streams_safe()
    sync_games_safe()
    sync_releases_safe()
    sync_recommendations_safe()


def main() -> None:
    export_all()


if __name__ == "__main__":
    main()

