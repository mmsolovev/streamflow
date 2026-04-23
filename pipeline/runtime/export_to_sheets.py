"""
Runtime job: export data to Google Sheets UI.

Implementation lives in pipeline.delivery.*; this file is the stable pipeline entrypoint.
"""

from pipeline.delivery.sheets_sync import (
    sync_bot_info,
    sync_games_safe,
    sync_recommendations_safe,
    sync_releases_safe,
    sync_streams_safe,
)


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
