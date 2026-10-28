"""Gemini integration used as the primary AI provider."""

from __future__ import annotations

import asyncio
import os
import re

from google import genai
from google.genai import types

from utils.logger import get_logger

logger = get_logger("services.gemini")

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
REQUEST_TIMEOUT = 30
_DESCRIPTION_MAX_LENGTH = 170
_RE_CYRILLIC = re.compile(r"[а-яА-ЯёЁ]")

CHAT_SYSTEM_PROMPT = (
    "Отвечай на русском, кратко и по существу: не более 150 символов. "
    "Не используй нецензурные или запрещённые Twitch выражения. "
    "Откажись отвечать на вопросы о политике и религии. "
    "Не начинай с вводных фраз, не повторяй вопрос, не выдумывай факты и не используй Markdown. "
    "Если сведения могут быть устаревшими, прямо укажи это."
)

DESCRIPTION_SYSTEM_PROMPT = (
    "Ты пишешь короткие интересные описания видеоигр для русскоязычной аудитории. "
    "Перескажи английское описание, сохранив жанр и ключевые особенности. "
    "Верни только готовое описание на русском: максимум 170 символов, живой язык, без клише, "
    "канцеляризмов, заголовка, кавычек и пояснений. Не добавляй фактов, которых нет в исходном тексте."
)


class GeminiServiceError(RuntimeError):
    """Gemini could not return a usable response."""


def _client() -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise GeminiServiceError("GEMINI_API_KEY is not configured")
    return genai.Client(api_key=api_key)


async def _generate(contents: str, system_instruction: str, max_output_tokens: int) -> str:
    try:
        response = await asyncio.wait_for(
            _client().aio.models.generate_content(
                model=GEMINI_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.7,
                    max_output_tokens=max_output_tokens,
                ),
            ),
            timeout=REQUEST_TIMEOUT,
        )
        text = (response.text or "").strip()
    except Exception as exc:
        raise GeminiServiceError(f"Gemini request failed: {exc}") from exc

    if not text:
        raise GeminiServiceError("Gemini returned an empty response")
    return text


async def ask_gemini(user_prompt: str) -> str:
    """Answer a Twitch chat question using Gemini's chat constraints."""
    if not isinstance(user_prompt, str) or not user_prompt.strip():
        raise GeminiServiceError("Prompt must be a non-empty string")
    return await _generate(user_prompt.strip(), CHAT_SYSTEM_PROMPT, max_output_tokens=250)


def _is_valid_description(text: str) -> bool:
    normalized = " ".join(text.split())
    refusal_markers = ("отказ", "не могу", "не могу помочь")
    return (
        bool(normalized)
        and len(normalized) <= _DESCRIPTION_MAX_LENGTH
        and bool(_RE_CYRILLIC.search(normalized))
        and not any(marker in normalized.casefold() for marker in refusal_markers)
    )


async def generate_short_description(english_summary: str, game_title: str | None = None) -> str | None:
    """Create a validated Russian game description from an IGDB summary."""
    if not isinstance(english_summary, str) or len(english_summary.strip()) < 10:
        return None

    title = game_title.strip() if isinstance(game_title, str) and game_title.strip() else "не указано"
    prompt = f"Название игры: {title}\nАнглийское описание: {english_summary.strip()}"
    try:
        result = " ".join((await _generate(prompt, DESCRIPTION_SYSTEM_PROMPT, 250)).split())
    except GeminiServiceError as exc:
        logger.warning("Gemini description generation failed for %r: %s", title, exc)
        return None

    if not _is_valid_description(result):
        logger.warning("Gemini returned an invalid description for %r", title)
        return None
    return result
