from __future__ import annotations

"""
Orchestrator job: import / cleanup IGDB-based recommendations in DB.
"""

import argparse
import asyncio
from datetime import datetime, timezone

from database.db import SessionLocal
from database.models import RecommendedGame, RecommendedGameVote
from pipeline.ingest.igdb_api import ingest_recommendation_metadata, ingest_top_upcoming_games
from pipeline.load.load_recommendations import (
    add_igdb_vote,
    create_igdb_recommendation,
    existing_recommendation_titles,
    find_recommendation_by_normalized_name,
)
from pipeline.transform.recommendations_transform import normalize_recommendation_name
from services.recommendations_service import STATUS_RELEASED, STATUS_UPCOMING


def import_igdb_games(*, limit: int = 15) -> None:
    session = SessionLocal()
    try:
        games = asyncio.run(ingest_top_upcoming_games(limit=int(limit)))
        titles = existing_recommendation_titles(session)

        added = 0
        now = datetime.now(timezone.utc)

        for meta in games:
            normalized = normalize_recommendation_name(meta.title)
            if not meta.title or meta.title in titles:
                continue

            existing = find_recommendation_by_normalized_name(session, normalized)
            if existing:
                continue

            rec = create_igdb_recommendation(
                session,
                normalized_name=normalized,
                title=meta.title,
                status=STATUS_UPCOMING,
                release_date=meta.release_date,
                steam_url=meta.steam_url,
                rating_text=meta.rating_text,
                platforms_text=meta.platforms_text,
                genres_text=meta.genres_text,
                cover_url=meta.cover_url,
                source_name=meta.source_name,
                source_game_id=meta.source_game_id,
                source_payload=meta.source_payload,
                now=now,
            )
            add_igdb_vote(session, recommended_game_id=int(rec.id), now=now)
            added += 1

        session.commit()
        print(f"IGDB import: added {added} games")
    finally:
        session.close()


def cleanup_igdb_recommendations() -> None:
    session = SessionLocal()
    try:
        today = datetime.utcnow().date()
        recommendations = (
            session.query(RecommendedGame)
            .join(RecommendedGame.votes)
            .filter(RecommendedGameVote.user_login == "igdb")
            .all()
        )

        removed = 0
        moved = 0

        for rec in recommendations:
            if not rec.release_date:
                continue

            if rec.release_date.date() <= today:
                if not rec.streamer_interested:
                    session.delete(rec)
                    removed += 1
                else:
                    rec.status = STATUS_RELEASED
                    moved += 1

                    for vote in rec.votes:
                        if vote.user_login == "igdb":
                            vote.user_login = "tabula"
                            vote.user_display_name = "Tabula"

        session.commit()
        print(f"IGDB cleanup: removed {removed}, moved {moved}")
    finally:
        session.close()


def cleanup_and_fix_igdb_games() -> None:
    session = SessionLocal()
    try:
        games = session.query(RecommendedGame).filter(RecommendedGame.source_name == "igdb").all()
        removed = 0
        updated = 0

        for game in games:
            # 1) remove without platforms
            if not game.platforms_text:
                session.delete(game)
                removed += 1
                continue

            # 2) if missing steam_url -> try to refetch
            if not game.steam_url:
                try:
                    meta = asyncio.run(ingest_recommendation_metadata(game.title))
                    if meta and meta.steam_url:
                        game.steam_url = meta.steam_url
                        game.updated_at = datetime.utcnow()
                        updated += 1
                except Exception as e:
                    print(f"[IGDB FIX ERROR] {game.title}: {e}")

        session.commit()
        print(f"IGDB cleanup done: removed={removed}, updated={updated}")
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="IGDB recommendations maintenance.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("import", help="Import top upcoming IGDB games into DB.")
    p.add_argument("--limit", type=int, default=15)

    sub.add_parser("cleanup", help="Remove/move IGDB recommendations based on release date + interest.")
    sub.add_parser("fix", help="Cleanup and fix IGDB games (platforms required; fill steam_url).")

    args = parser.parse_args()
    if args.cmd == "import":
        import_igdb_games(limit=int(args.limit))
    elif args.cmd == "cleanup":
        cleanup_igdb_recommendations()
    elif args.cmd == "fix":
        cleanup_and_fix_igdb_games()
    else:
        raise SystemExit(f"Unknown cmd: {args.cmd}")


if __name__ == "__main__":
    main()

