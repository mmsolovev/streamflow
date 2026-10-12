"""Поиск VOD завершившегося стрима по точному Twitch `stream_id`.

Ключевой момент: VOD ищем **по stream_id**, а не по времени или по названию.
После краша трансляции у стримера появляется новый broadcast с новым
`stream_id` и своим VOD, и только точное совпадение отличает его от VOD
предыдущего стрима.

`stream_id` — строка: формат Twitch исторически строковый, и int-гипотеза
уже ломалась бы на очень больших значениях.
"""

from __future__ import annotations

import re
from typing import Any

import aiohttp

from pipeline.ingest.twitch_api import (
    TwitchTokenExpiredError,
    fetch_user_id,
    fetch_vods,
)
from services.token_service import get_current_tokens, try_refresh_token
from utils.logger import get_logger


logger = get_logger("telegram.vod")

# Сколько последних записей канала смотреть. Свежий стрим всегда в первых
# страницах архива; двадцати с запасом хватает, даже если стример вёл
# несколько коротких сессий подряд.
MAX_ITEMS = 20


class VodLookupError(Exception):
    """Ошибка инфраструктуры — задачу нужно повторить позже."""


def _duration_seconds(value: Any) -> int:
    """`"1h2m3s"` -> 3723. Twitch отдаёт длительность строкой в этом формате."""
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)

    text = str(value)
    match = re.fullmatch(
        r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?",
        text,
    )
    if not match:
        return 0

    hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def _duration_minutes(value: Any) -> int | None:
    # Не round(): в Python round(62.5) == 62 из-за округления к чётному,
    # и длительность показывалась бы на минуту меньше фактической.
    seconds = _duration_seconds(value)
    return int(seconds / 60 + 0.5) if seconds else None


def _vod_url(vod: dict[str, Any]) -> str | None:
    """Ссылка на запись.

    `url` из Twitch — полная ссылка на страницу, `id` нужен для отсечения
    самой ссылки: id всегда есть, url — тоже, но не в каждом ответе.
    """
    explicit = vod.get("url")
    if explicit:
        return str(explicit)

    vod_id = vod.get("id")
    if vod_id is None:
        return None

    login = vod.get("channel_login")
    if not login:
        return None

    return f"https://www.twitch.tv/{login}/videos/{vod_id}"


def pick_vod_for_stream(vods: list[dict[str, Any]], stream_id: str) -> dict[str, Any] | None:
    """VOD нужного стрима, либо None если его в архиве нет.

    У одного stream_id бывает несколько записей ( Twitch иногда отдаёт
    повторную обработку), поэтому берём самую длинную — это и есть
    полноценная запись.
    """
    wanted = str(stream_id)
    candidates = [vod for vod in vods if str(vod.get("stream_id")) == wanted]
    if not candidates:
        return None

    return max(candidates, key=lambda vod: _duration_seconds(vod.get("duration")))


async def fetch_vod_for_stream(
    *,
    session: aiohttp.ClientSession,
    channel_login: str,
    stream_id: str,
    client_id: str,
) -> dict[str, Any] | None:
    """VOD стрима или None. Ошибки сети/токена поднимает как VodLookupError.

    None означает «Twitch ответил успешно, но такого VOD нет» — это бизнес-
    исход, который дальше становится `no_vod`. Исключение означает «не
    вышло проверить» — задача уйдёт в ретрай.
    """
    access_token, _ = get_current_tokens()
    if not access_token:
        raise VodLookupError("нет Twitch access token")

    user_id = await _fetch_user_id(
        session,
        channel_login=channel_login,
        client_id=client_id,
        access_token=access_token,
    )

    vods = await _fetch_vods(
        session,
        user_id=user_id,
        client_id=client_id,
        access_token=access_token,
    )

    vod = pick_vod_for_stream(vods, stream_id)
    if vod is None:
        return None

    return {
        "vod_id": str(vod.get("id")),
        "url": _vod_url(vod),
        "duration_minutes": _duration_minutes(vod.get("duration")),
        "created_at": vod.get("created_at"),
        "published_at": vod.get("published_at"),
    }


async def _fetch_user_id(
    session: aiohttp.ClientSession,
    *,
    channel_login: str,
    client_id: str,
    access_token: str,
) -> str:
    """user_id канала с одним ретраем на протухшем токене.

    401 от Twitch означает, что access token истёк; обновляем и повторяем
    ровно один раз, чтобы не зациклиться на битом refresh token.
    """
    try:
        return await fetch_user_id(
            session,
            client_id=client_id,
            access_token=access_token,
            channel_login=channel_login,
        )
    except TwitchTokenExpiredError:
        logger.warning("Twitch token expired while fetching user_id, refreshing")

    refreshed = await try_refresh_token()
    if not refreshed:
        raise VodLookupError("не удалось обновить Twitch access token")

    return await fetch_user_id(
        session,
        client_id=client_id,
        access_token=refreshed,
        channel_login=channel_login,
    )


async def _fetch_vods(
    session: aiohttp.ClientSession,
    *,
    user_id: str,
    client_id: str,
    access_token: str,
) -> list[dict[str, Any]]:
    """Верхушка архива канала, с тем же ретраем на 401."""
    try:
        return await fetch_vods(
            session,
            client_id=client_id,
            access_token=access_token,
            user_id=user_id,
            first=100,
            max_items=MAX_ITEMS,
        )
    except TwitchTokenExpiredError:
        logger.warning("Twitch token expired while fetching vods, refreshing")

    refreshed = await try_refresh_token()
    if not refreshed:
        raise VodLookupError("не удалось обновить Twitch access token")

    return await fetch_vods(
        session,
        client_id=client_id,
        access_token=refreshed,
        user_id=user_id,
        first=100,
        max_items=MAX_ITEMS,
    )


__all__ = [
    "MAX_ITEMS",
    "VodLookupError",
    "fetch_vod_for_stream",
    "pick_vod_for_stream",
]
