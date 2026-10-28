"""AI provider facade: Gemini first, then OpenRouter, then legacy g4f."""

from __future__ import annotations

import asyncio
import re

from g4f import ChatCompletion

from services.gemini_service import CHAT_SYSTEM_PROMPT, DESCRIPTION_SYSTEM_PROMPT, ask_gemini
from utils.logger import get_logger

logger = get_logger("services.gpt")

GPT_TIMEOUT = 30
_DESCRIPTION_MAX_LENGTH = 170
_RE_CYRILLIC = re.compile(r"[а-яА-ЯёЁ]")


def _is_likely_russian(text: str) -> bool:
    return bool(_RE_CYRILLIC.search(text))


def _valid_description(text: str | None) -> str | None:
    if not text:
        return None
    normalized = " ".join(text.split())
    if len(normalized) > _DESCRIPTION_MAX_LENGTH or not _is_likely_russian(normalized):
        return None
    if any(marker in normalized.casefold() for marker in ("отказ", "не могу", "не могу помочь")):
        return None
    return normalized


async def _ask_g4f(prompt: str) -> str | None:
    def request() -> str:
        return ChatCompletion.create(
            model="",
            messages=[
                {"role": "system", "content": CHAT_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )

    try:
        answer = await asyncio.wait_for(asyncio.to_thread(request), timeout=GPT_TIMEOUT)
    except Exception as exc:
        logger.warning("g4f chat request failed: %s", exc)
        return None
    return " ".join(answer.split()) if answer else None


async def ask_gpt(prompt: str) -> str:
    """Get a chat reply; Gemini is primary and providers fall back in order."""
    try:
        answer = await ask_gemini(prompt)
        if answer:
            return answer
    except Exception as exc:
        logger.warning("Gemini chat request failed, trying OpenRouter: %s", exc)

    try:
        from services.openrouter_service import ask_openrouter
        answer = await ask_openrouter(prompt)
        if answer:
            return answer
    except Exception as exc:
        logger.warning("OpenRouter chat request failed, trying g4f: %s", exc)

    answer = await _ask_g4f(prompt)
    if answer:
        return answer
    raise RuntimeError("All AI providers failed")


async def _generate_description_with_g4f(summary: str, title: str | None) -> str | None:
    game_title = title.strip() if isinstance(title, str) and title.strip() else "не указано"
    prompt = f"Название игры: {game_title}\nАнглийское описание: {summary.strip()}"

    def request() -> str:
        return ChatCompletion.create(
            model="",
            messages=[
                {"role": "system", "content": DESCRIPTION_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )

    try:
        answer = await asyncio.wait_for(asyncio.to_thread(request), timeout=GPT_TIMEOUT)
    except Exception as exc:
        logger.warning("g4f description request failed: %s", exc)
        return None
    return _valid_description(answer)


async def generate_short_description(text: str, game_title: str | None = None) -> str | None:
    """Generate a short Russian description: Gemini -> OpenRouter -> g4f."""
    if not isinstance(text, str) or len(text.strip()) < 10:
        return None

    from services.gemini_service import generate_short_description as gemini_generate
    answer = await gemini_generate(text, game_title)
    if answer:
        return answer

    try:
        from services.openrouter_service import generate_short_description as openrouter_generate
        answer = await openrouter_generate(text, game_title)
        if answer:
            return answer
    except Exception as exc:
        logger.warning("OpenRouter description generation failed, trying g4f: %s", exc)

    return await _generate_description_with_g4f(text, game_title)
