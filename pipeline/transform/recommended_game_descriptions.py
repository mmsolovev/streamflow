from __future__ import annotations

"""
Transform layer: build short Russian descriptions for recommended games.

This module does not touch the database. It only produces derived text.
"""

import asyncio

import g4f


def _generate_short_description_sync(text: str, *, model: str = "") -> str | None:
    try:
        result = g4f.ChatCompletion.create(
            model=model,
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

    cleaned = " ".join(str(result).split())
    return cleaned[:235]


async def generate_short_description(text: str, *, model: str = "") -> str | None:
    return await asyncio.to_thread(_generate_short_description_sync, text, model=model)


__all__ = ["generate_short_description"]

