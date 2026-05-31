import asyncio
import re

import g4f

from utils.logger import get_logger

logger = get_logger("services.gpt")

# Models are tried in order on each retry to hit different g4f providers.
GPT_MODELS = ["", "openai", "gpt-4"]
GPT_TIMEOUT = 30
MAX_RETRIES = len(GPT_MODELS)

# At least one Cyrillic letter is required to consider the result Russian.
_RE_CYRILLIC = re.compile(r"[а-яА-ЯёЁ]")


async def ask_gpt(prompt: str) -> str:
    loop = asyncio.get_running_loop()

    def sync_request():
        return g4f.ChatCompletion.create(
            model="",
            messages=[
                {
                    "role": "system",
                    "content": "Отвечай кратко, не более 150 символов. Не используй непристойные слова и запрещённые "
                               "на Twitch выражения. Откажись отвечать, если вопрос касается политики или религии."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
        )

    return await loop.run_in_executor(None, sync_request)


async def _gpt_request(system_prompt: str, user_text: str, model: str) -> str | None:
    """Makes a single g4f request with the given model. Returns None on failure."""
    loop = asyncio.get_running_loop()

    def sync_request():
        return g4f.ChatCompletion.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
        )

    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(None, sync_request),
            timeout=GPT_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.warning("GPT request timed out after %ss (model=%s)", GPT_TIMEOUT, model)
        return None
    except Exception as e:
        logger.warning("GPT request failed (model=%s): %s", model, e)
        return None

    if not result:
        logger.warning("GPT returned empty result (model=%s)", model)
        return None

    result = " ".join(result.split())
    return result


def _is_likely_russian(text: str) -> bool:
    """Returns True if the text contains at least one Cyrillic character."""
    return bool(_RE_CYRILLIC.search(text))


async def generate_short_description(text: str) -> str | None:
    system_prompt = (
        "Ты переводишь описание игры с английского на русский язык. "
        "Отвечай ТОЛЬКО на русском языке. "
        "Краткий пересказ, максимум 170 символов. Без лишней воды."
    )

    for attempt, model in enumerate(GPT_MODELS, start=1):
        logger.info(
            "Generating description (attempt %d/%d, model=%s)",
            attempt, MAX_RETRIES, model,
        )
        raw = await _gpt_request(system_prompt, text, model)
        if not raw:
            if attempt < MAX_RETRIES:
                wait = 2 ** attempt
                logger.warning("Retrying with next model in %ds...", wait)
                await asyncio.sleep(wait)
            continue

        shortened = raw[:170]

        if not _is_likely_russian(shortened):
            logger.warning(
                "Description not in Russian, skipping (model=%s, length=%d, preview=%r)",
                model, len(raw), shortened[:80],
            )
            if attempt < MAX_RETRIES:
                wait = 2 ** attempt
                logger.warning("Retrying with next model in %ds...", wait)
                await asyncio.sleep(wait)
            continue

        logger.info(
            "Description generated (model=%s, raw_length=%d, short_length=%d)",
            model, len(raw), len(shortened),
        )
        return shortened

    logger.warning(
        "generate_short_description failed after %d attempts (models=%s, input length=%d)",
        MAX_RETRIES, GPT_MODELS, len(text),
    )
    return None
