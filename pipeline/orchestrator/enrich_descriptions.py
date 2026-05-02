from __future__ import annotations

"""
Orchestrator job: fill short descriptions for recommended games.

Ingest: uses summary from RecommendedGame.source_payload (already stored in DB).
Transform: asks AI to produce a short Russian description.
Load: writes RecommendedGame.description_short back to DB.
"""

import argparse
import asyncio
import json

from database.db import SessionLocal
from pipeline.load.load_recommendations import iter_games_missing_short_description, set_game_short_description
from services.gpt_service import generate_short_description


async def async_run(
    *,
    limit: int = 0,
    dry_run: bool = False,
    delay_seconds: float = 1.5,
    model: str = "",
) -> None:
    session = SessionLocal()
    try:
        games = list(iter_games_missing_short_description(session, limit=int(limit)))
        print(f"Found games missing description_short: {len(games)}")

        updated = 0
        skipped = 0

        for i, game in enumerate(games, 1):
            try:
                payload_raw = game.source_payload
                if not payload_raw:
                    skipped += 1
                    continue

                payload = json.loads(payload_raw)
                summary = payload.get("summary")
                if not summary:
                    skipped += 1
                    continue

                short = await generate_short_description(str(summary), model=model)
                if not short:
                    print(f"[{i}] skip (ai): {game.title}")
                    skipped += 1
                    continue

                changed = set_game_short_description(session, game, short)
                if not changed:
                    skipped += 1
                    continue

                updated += 1

                if dry_run:
                    session.rollback()
                    print(f"[{i}] DRY-RUN: {game.title}")
                else:
                    session.commit()
                    print(f"[{i}] OK: {game.title}")

                if float(delay_seconds) > 0:
                    await asyncio.sleep(float(delay_seconds))
            except Exception as e:
                print(f"[{i}] ERROR: {game.title} -> {e}")
                session.rollback()
                continue

        print(f"Done. Updated: {updated}. Skipped: {skipped}. Dry run: {'yes' if dry_run else 'no'}.")
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Fill RecommendedGame.description_short using AI (best-effort).")
    parser.add_argument("--limit", type=int, default=0, help="Max games to process (0 = no limit).")
    parser.add_argument("--dry-run", action="store_true", help="Do not commit changes to DB.")
    parser.add_argument("--delay-seconds", type=float, default=1.5, help="Delay between requests.")
    parser.add_argument("--model", default="", help="Optional provider model name (passed to g4f).")
    args = parser.parse_args()
    asyncio.run(
        async_run(
            limit=int(args.limit),
            dry_run=bool(args.dry_run),
            delay_seconds=float(args.delay_seconds),
            model=str(args.model or ""),
        )
    )


if __name__ == "__main__":
    main()
