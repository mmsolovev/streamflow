"""
Legacy script kept for backwards compatibility.

Old location: pipeline/transform/twitch_data.py
New preferred entrypoint: pipeline/runtime/sync_stream_vods.py
"""

from pipeline.runtime.sync_stream_vods import main  # noqa: F401


if __name__ == "__main__":
    main()

