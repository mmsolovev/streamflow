"""
Legacy entrypoint kept for backwards compatibility.

Prefer running: `python pipeline/runtime/sync_twitchtracker_html_to_db.py`.
"""

from pipeline.runtime.sync_twitchtracker_html_to_db import main, run  # noqa: F401


if __name__ == "__main__":
    main()

