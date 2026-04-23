"""
Legacy entrypoint kept for backwards compatibility.

Prefer: `python pipeline/runtime/enrich_streams_genres.py`.
"""

from pipeline.runtime.enrich_streams_genres import main  # noqa: F401


if __name__ == "__main__":
    main()

