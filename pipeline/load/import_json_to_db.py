"""
Legacy entrypoint kept for backwards compatibility.

Prefer: `python pipeline/runtime/import_twitchtracker_json_to_db.py`.
"""

from pipeline.runtime.import_twitchtracker_json_to_db import main, run  # noqa: F401


if __name__ == "__main__":
    main()

