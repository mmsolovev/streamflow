from __future__ import annotations

"""
Single entrypoint for running pipeline scenarios.

This is the main CLI, the "control panel" for the data pipeline.
It uses `argparse` to define commands and arguments, and then calls the
appropriate orchestrator function from the `pipeline.orchestrator` package.

The orchestrators are responsible for the high-level flow, while the
actual business logic resides in the ingest/transform/load/delivery layers.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from pipeline.orchestrator.context import PipelineContext


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv

    # A "parent" parser for arguments that are common to many commands
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument("--dry-run", action="store_true", help="Do not commit changes to the database.")

    parser = argparse.ArgumentParser(prog="pipeline", description="Pipeline orchestrator CLI.")
    sub = parser.add_subparsers(dest="command", required=True, help="The pipeline command to run.")

    # --- Sync HTML/JSON from TwitchTracker ---
    p = sub.add_parser("sync-html", help="Parse TwitchTracker HTML pages and sync into DB.", parents=[common_parser])
    p.add_argument("--prune", action="store_true", help="Delete DB rows missing in parsed dataset.")
    p.add_argument("--pages-dir", type=Path, help="Directory with TwitchTracker HTML pages (default: storage/pages).")
    p.add_argument("--write-json", action="store_true", help="Also write datasets to storage/*.json.")
    p.add_argument("--merge-json", action="store_true", help="Merge streams.json into existing file.")

    p = sub.add_parser("import-json", help="Import storage/*.json into DB.", parents=[common_parser])
    p.add_argument("--streams-path", type=Path, help="Path to streams.json (default: storage/streams.json).")
    p.add_argument("--games-path", type=Path, help="Path to games.json (default: storage/games.json).")
    p.add_argument("--no-prune", action="store_true", help="Do not delete DB rows missing from JSON.")

    p = sub.add_parser("sync-new-stream", help="Sync one new stream into DB.", parents=[common_parser])
    p.add_argument("stream_html", type=Path, help="Path to TwitchTracker HTML for the new stream.")
    p.add_argument("--games-html", type=Path, help="Path to games_page HTML (optional).")
    p.add_argument("--write-json", action="store_true", help="Also mirror into storage/*.json as a backup.")

    # --- Sync from APIs and Sheets ---
    p = sub.add_parser("sync-vods", help="Fetch VODs from Twitch API and sync Stream.vod_url.", parents=[common_parser])
    p = sub.add_parser("import-sheets", help="Import manual fields from Google Sheets into DB.", parents=[common_parser])
    p = sub.add_parser("export-sheets", help="Export DB state to Google Sheets.", parents=[common_parser])
    p = sub.add_parser("import-igdb-upcoming", help="Import upcoming games from IGDB.", parents=[common_parser])
    p.add_argument("--limit", type=int, default=15, help="Number of games to fetch.")

    # --- Enrichment Jobs ---
    p = sub.add_parser("enrich-genres", help="Compute streams.genres_text.", parents=[common_parser])
    p.add_argument("--limit", type=int, default=0, help="Max streams to process (0 = no limit).")
    p.add_argument("--only-stream-id", type=int, default=0, help="Process only this stream id.")
    p.add_argument("--force", action="store_true", help="Recompute even if genres_text is not blank.")

    p = sub.add_parser("enrich-games", help="Enrich games_meta with HLTB and IGDB data.", parents=[common_parser])
    p.add_argument("--limit", type=int, default=25, help="Max games to process.")
    p.add_argument("--only-game-id", type=int, default=0, help="Process only this game ID.")
    p.add_argument("--force", action="store_true", help="Re-enrich even if data is already present.")

    p = sub.add_parser("enrich-descriptions", help="Fill short descriptions for games (AI).", parents=[common_parser])
    p.add_argument("--limit", type=int, default=10, help="Max descriptions to generate.")

    # --- Argument Parsing ---
    args = parser.parse_args(argv)
    command = args.command

    # --- Command Execution ---
    try:
        with PipelineContext(dry_run=getattr(args, "dry_run", False)) as context:
            if command == "sync-html":
                from pipeline.orchestrator.sync_twitchtracker_html_to_db import run
                run(context, prune=args.prune, pages_dir=args.pages_dir, write_json=args.write_json, merge_json=args.merge_json)

            elif command == "import-json":
                from pipeline.orchestrator.import_twitchtracker_json_to_db import run
                run(context, streams_path=args.streams_path, games_path=args.games_path, prune=not args.no_prune)

            elif command == "sync-new-stream":
                from pipeline.orchestrator.sync_new_stream import run
                run(context, stream_html=args.stream_html, games_html=args.games_html, write_json=args.write_json)

            elif command == "sync-vods":
                from pipeline.orchestrator.sync_stream_vods import run
                asyncio.run(run(context))

            elif command == "import-sheets":
                from pipeline.orchestrator.import_manual_fields_from_sheets import run
                run(context)

            elif command == "export-sheets":
                from pipeline.orchestrator.export_to_sheets import run
                run(context)

            elif command == "import-igdb-upcoming":
                from pipeline.orchestrator.igdb_import import run
                asyncio.run(run(context, limit=args.limit))

            elif command == "enrich-genres":
                from pipeline.orchestrator.enrich_streams_genres import run
                run(context, limit=args.limit, only_stream_id=args.only_stream_id, force=args.force)

            elif command == "enrich-games":
                from pipeline.orchestrator.enrich_games_meta import run
                asyncio.run(run(context, limit=args.limit, only_game_id=args.only_game_id, force=args.force))

            elif command == "enrich-descriptions":
                from pipeline.orchestrator.enrich_descriptions import run
                asyncio.run(run(context, limit=args.limit))

    except Exception as e:
        print(f"Pipeline command '{command}' failed: {e}", file=sys.stderr)
        return 1

    print(f"Pipeline command '{command}' finished successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
