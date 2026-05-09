from pipeline.delivery.sheets_bot_info import sync_bot_info
from pipeline.delivery.sheets_games import sync_games_safe
from pipeline.delivery.sheets_recommendations import sync_recommendations_safe
from pipeline.delivery.sheets_releases import sync_releases_safe
from pipeline.delivery.sheets_streams import sync_streams_safe


def run_all_sheets_sync():
    """
    Orchestrates the synchronization of various data entities from the database
    to Google Sheets.
    """
    print("Starting Google Sheets synchronization...")

    # Synchronize bot information (commands, etc.) - currently commented out as in old script
    # sync_bot_info()

    # Synchronize streams data to Google Sheets
    sync_streams_safe()

    # Synchronize games data to Google Sheets
    sync_games_safe()

    # Synchronize upcoming game releases to Google Sheets
    sync_releases_safe()

    # Synchronize game recommendations (released games) to Google Sheets
    sync_recommendations_safe()

    print("Google Sheets synchronization completed.")


if __name__ == "__main__":
    run_all_sheets_sync()
