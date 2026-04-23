"""
Legacy entrypoint kept for backwards compatibility.

Prefer: `python pipeline/runtime/enrich_games_meta.py`.
"""

from pipeline.runtime.enrich_games_meta import main  # noqa: F401


if __name__ == "__main__":
    main()

