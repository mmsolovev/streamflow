from __future__ import annotations

"""
Orchestrator job: compute streams.genres_text.

Transform logic lives in `pipeline.transform.streams_transform`.
DB interactions live in `pipeline.load.load_streams`.
"""

import argparse

from database.db import SessionLocal
from pipeline.load.load_streams import get_stream_context, iter_streams_for_genres, set_stream_genres_text
from pipeline.transform.streams_transform import compute_stream_genres
from pipeline.transform.utils_transform import normalize_key


def run(*, dry_run: bool = False, limit: int = 0, only_stream_id: int = 0, force: bool = False) -> None:
    session = SessionLocal()
    try:
        streams = iter_streams_for_genres(
            session,
            only_stream_id=int(only_stream_id),
            limit=int(limit),
            force=bool(force),
        )

        # Extra blank filtering for rows containing only whitespace.
        if not force and not only_stream_id:
            streams = [s for s in streams if not (getattr(s, "genres_text", None) or "").strip()]

        if not streams:
            print("Nothing to do: no streams selected.")
            return

        updated = 0

        for idx, stream in enumerate(streams, start=1):
            has_participants, game_names, game_genres_texts = get_stream_context(stream)
            new_value = compute_stream_genres(
                title=getattr(stream, "title", None),
                has_participants=has_participants,
                game_names=game_names,
                game_genres_texts=game_genres_texts,
            )

            old_value = getattr(stream, "genres_text", None)
            if normalize_key(new_value or "") == normalize_key(old_value or ""):
                continue

            updated += 1
            print(f"[{idx}/{len(streams)}] stream_id={int(stream.id)}: {new_value!r}")

            if not dry_run:
                set_stream_genres_text(session, stream, new_value)

        if dry_run:
            session.rollback()
        else:
            session.commit()

        print(f"{'DRY-RUN' if dry_run else 'APPLIED'}: updated_streams={updated}")
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Fill streams.genres_text from games + rules (only if blank).")
    parser.add_argument("--dry-run", action="store_true", help="Do not commit changes to DB.")
    parser.add_argument("--limit", type=int, default=0, help="Max streams to process (0 = no limit).")
    parser.add_argument("--only-stream-id", type=int, default=0, help="Process only this stream id.")
    parser.add_argument("--force", action="store_true", help="Recompute even if streams.genres_text is not blank.")
    args = parser.parse_args()

    run(
        dry_run=bool(args.dry_run),
        limit=int(args.limit),
        only_stream_id=int(args.only_stream_id),
        force=bool(args.force),
    )


if __name__ == "__main__":
    main()

