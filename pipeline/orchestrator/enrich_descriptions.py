from __future__ import annotations

"""
Orchestrator job: fill short descriptions for recommended games using AI.

Note: this uses `g4f` directly. Treat as a best-effort enrichment tool.
"""

import asyncio
import json

from database.db import SessionLocal
from database.models import RecommendedGame

import g4f


def generate_short_description_sync(text: str) -> str | None:
    """Generate a short Russian summary for a game's description (best-effort)."""
    try:
        result = g4f.ChatCompletion.create(
            model="",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Translate and briefly summarize the game description in Russian. "
                        "Max 170 characters. No filler."
                    ),
                },
                {"role": "user", "content": text},
            ],
        )
    except Exception:
        return None

    if not result:
        return None

    result = " ".join(str(result).split())
    return result[:235]


async def process() -> None:
    session = SessionLocal()
    try:
        games = session.query(RecommendedGame).filter(RecommendedGame.description_short.is_(None)).all()
        print(f"Found games: {len(games)}")

        for i, game in enumerate(games, 1):
            try:
                if not game.source_payload:
                    continue

                payload = json.loads(game.source_payload)
                summary = payload.get("summary")
                if not summary:
                    continue

                short = await asyncio.to_thread(generate_short_description_sync, summary)
                if not short:
                    print(f"[{i}] skip: {game.title}")
                    continue

                game.description_short = short
                session.commit()
                print(f"[{i}] OK: {game.title}")

                await asyncio.sleep(1.5)
            except Exception as e:
                print(f"[{i}] ERROR: {game.title} -> {e}")
                continue
    finally:
        session.close()


def main() -> None:
    asyncio.run(process())


if __name__ == "__main__":
    main()

