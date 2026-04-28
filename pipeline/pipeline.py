from __future__ import annotations

"""
Single entrypoint for running pipeline scenarios.

This is orchestration glue: it wires together jobs from `pipeline.orchestrator.*`.
Business logic remains in ingest/transform/load/delivery.
"""

import argparse
import asyncio
import sys
from pathlib import Path


def _project_root() -> Path:
    # .../pipeline/pipeline.py -> project root
    return Path(__file__).resolve().parents[1]


def _cmd_sync_twitchtracker_html_to_db(ns: argparse.Namespace) -> int:
    from pipeline.orchestrator.sync_twitchtracker_html_to_db import run

    run(
        dry_run=bool(ns.dry_run),
        prune=bool(ns.prune),
        pages_dir=Path(ns.pages_dir) if ns.pages_dir else None,
        write_json=bool(ns.write_json),
        merge_json=bool(ns.merge_json),
        streams_json_path=Path(ns.streams_json_path) if ns.streams_json_path else None,
        games_json_path=Path(ns.games_json_path) if ns.games_json_path else None,
    )
    return 0


def _cmd_import_twitchtracker_json_to_db(ns: argparse.Namespace) -> int:
    from pipeline.orchestrator.import_twitchtracker_json_to_db import run

    run(
        streams_path=Path(ns.streams_path) if ns.streams_path else None,
        games_path=Path(ns.games_path) if ns.games_path else None,
        dry_run=bool(ns.dry_run),
        prune=not bool(ns.no_prune),
        sync_participants_from_title=not bool(ns.no_sync_participants),
    )
    return 0


def _cmd_sync_stream_vods(ns: argparse.Namespace) -> int:
    from pipeline.orchestrator.sync_stream_vods import async_run

    asyncio.run(async_run(dry_run=bool(ns.dry_run)))
    return 0


def _cmd_export_to_sheets(_: argparse.Namespace) -> int:
    from pipeline.orchestrator.export_to_sheets import export_all

    export_all()
    return 0


def _cmd_import_manual_fields_from_sheets(_: argparse.Namespace) -> int:
    from pipeline.orchestrator.import_manual_fields_from_sheets import import_all_manual_fields

    import_all_manual_fields()
    return 0


def _cmd_enrich_descriptions(_: argparse.Namespace) -> int:
    from pipeline.orchestrator.enrich_descriptions import async_run

    asyncio.run(async_run())
    return 0


def _cmd_sync_new_stream(ns: argparse.Namespace) -> int:
    from pipeline.orchestrator.sync_new_stream import run

    run(
        stream_html=Path(ns.stream_html),
        games_html=Path(ns.games_html) if ns.games_html else None,
        pages_dir=Path(ns.pages_dir) if ns.pages_dir else None,
        dry_run=bool(ns.dry_run),
        write_json=bool(ns.write_json),
        merge_streams_json=not bool(ns.no_merge_streams_json),
        streams_json_path=Path(ns.streams_json_path) if ns.streams_json_path else None,
        games_json_path=Path(ns.games_json_path) if ns.games_json_path else None,
        update_genres_for_stream=not bool(ns.no_update_genres),
    )
    return 0


def _cmd_passthrough(module: str, extra_argv: list[str]) -> int:
    """
    For jobs that already implement their own argparse in module.main().
    We forward CLI args after `--`.
    """
    mod = __import__(module, fromlist=["main"])
    if not hasattr(mod, "main"):
        raise SystemExit(f"Module {module} has no main()")

    prev = sys.argv
    try:
        sys.argv = [f"{module}.py", *extra_argv]
        mod.main()
        return 0
    finally:
        sys.argv = prev


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    parser = argparse.ArgumentParser(prog="pipeline", description="Pipeline orchestrator CLI.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # --- TwitchTracker HTML -> DB (optionally JSON mirror) ---
    p = sub.add_parser("sync-html", help="Parse TwitchTracker HTML pages and sync into DB.")
    p.add_argument("--dry-run", action="store_true", help="Do not commit changes to DB.")
    p.add_argument("--prune", action="store_true", help="Delete DB rows missing in parsed dataset.")
    p.add_argument("--pages-dir", default="", help="Directory with TwitchTracker HTML pages (default: storage/pages).")
    p.add_argument("--write-json", action="store_true", help="Also write datasets to storage/*.json.")
    p.add_argument("--merge-json", action="store_true", help="Merge streams.json into existing file.")
    p.add_argument("--streams-json-path", default="", help="Override output path for streams.json.")
    p.add_argument("--games-json-path", default="", help="Override output path for games.json.")
    p.set_defaults(func=_cmd_sync_twitchtracker_html_to_db)

    # --- Single new stream -> DB ---
    p = sub.add_parser("sync-new-stream", help="Sync one new stream (stream HTML + games HTML) into DB.")
    p.add_argument("--stream-html", required=True, help="Path to TwitchTracker HTML for the new stream.")
    p.add_argument("--games-html", default="", help="Path to games_page HTML (all games). If empty, auto-pick from --pages-dir.")
    p.add_argument("--pages-dir", default="", help="Directory to auto-pick latest games_page*.html (default: storage/pages).")
    p.add_argument("--dry-run", action="store_true", help="Do not commit changes to DB.")
    p.add_argument("--write-json", action="store_true", help="Also mirror into storage/*.json as a backup.")
    p.add_argument("--no-merge-streams-json", action="store_true", help="Overwrite streams.json instead of merging.")
    p.add_argument("--streams-json-path", default="", help="Override output path for streams.json.")
    p.add_argument("--games-json-path", default="", help="Override output path for games.json.")
    p.add_argument("--no-update-genres", action="store_true", help="Do not recompute genres_text for the new stream.")
    p.set_defaults(func=_cmd_sync_new_stream)

    # --- Legacy JSON -> DB ---
    p = sub.add_parser("import-json", help="Import storage/streams.json + storage/games.json into DB.")
    p.add_argument("--dry-run", action="store_true", help="Do not commit changes to DB.")
    p.add_argument("--no-prune", action="store_true", help="Do not delete DB rows missing from JSON.")
    p.add_argument("--no-sync-participants", action="store_true", help="Do not sync participants from @mentions.")
    p.add_argument("--streams-path", default="", help="Path to streams.json (default: storage/streams.json).")
    p.add_argument("--games-path", default="", help="Path to games.json (default: storage/games.json).")
    p.set_defaults(func=_cmd_import_twitchtracker_json_to_db)

    # --- Twitch VOD URLs sync ---
    p = sub.add_parser("sync-vods", help="Fetch VODs from Twitch API and sync Stream.vod_url.")
    p.add_argument("--dry-run", action="store_true", help="Do not commit changes to DB.")
    p.set_defaults(func=_cmd_sync_stream_vods)

    # --- Sheets ---
    p = sub.add_parser("export-sheets", help="Export DB state to Google Sheets.")
    p.set_defaults(func=_cmd_export_to_sheets)

    p = sub.add_parser("import-sheets-manual", help="Import manual fields from Google Sheets into DB.")
    p.set_defaults(func=_cmd_import_manual_fields_from_sheets)

    # --- Enrichments ---
    p = sub.add_parser("enrich-descriptions", help="Fill short descriptions for RecommendedGame rows (AI).")
    p.set_defaults(func=_cmd_enrich_descriptions)

    # These jobs already parse their own args; we forward `-- ...`.
    p = sub.add_parser(
        "enrich-games-meta",
        help="Enrich games_meta in SQLite. Pass args after `--` to the underlying job.",
    )
    p.add_argument("args", nargs=argparse.REMAINDER)
    p.set_defaults(func=lambda ns: _cmd_passthrough("pipeline.orchestrator.enrich_games_meta", [a for a in ns.args if a != "--"]))

    p = sub.add_parser(
        "enrich-streams-genres",
        help="Compute streams.genres_text. Pass args after `--` to the underlying job.",
    )
    p.add_argument("--dry-run", action="store_true", help="Do not commit changes to DB.")
    p.add_argument("--limit", type=int, default=0, help="Max streams to process (0 = no limit).")
    p.add_argument("--only-stream-id", type=int, default=0, help="Process only this stream id.")
    p.add_argument("--force", action="store_true", help="Recompute even if streams.genres_text is not blank.")
    p.set_defaults(
        func=lambda ns: __import__("pipeline.orchestrator.enrich_streams_genres", fromlist=["run"]).run(
            dry_run=bool(ns.dry_run),
            limit=int(ns.limit),
            only_stream_id=int(ns.only_stream_id),
            force=bool(ns.force),
        )
        or 0
    )

    ns = parser.parse_args(argv)
    return int(ns.func(ns))


if __name__ == "__main__":
    raise SystemExit(main())
