import time

import aiohttp

from config.settings import TWITCH_PRIMARY_CHANNEL, CLIENT_ID, CLIENT_SECRET

_app_token_cache: dict = {"token": None, "expires_at": 0.0}
_game_cache: dict[str, tuple[float, dict | None]] = {}


async def get_current_game():
    url = f"https://api.twitch.tv/helix/streams?user_login={TWITCH_PRIMARY_CHANNEL}"
    headers = {
        "Client-ID": CLIENT_ID,
        "Authorization": f"Bearer {await get_app_access_token()}"
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as resp:
            data = await resp.json()
            if data.get("data"):
                return data["data"][0].get("game_name")
    return None


async def get_game_by_category_id(category_id: str | int) -> dict | None:
    """Fetch a Twitch category and its IGDB ID through Helix Get Games.

    Twitch's ``igdb_id`` is empty when Twitch has no known IGDB mapping.
    Positive responses are cached for six hours; misses are cached briefly.
    """
    category_id = str(category_id or "").strip()
    if not category_id:
        return None

    now = time.time()
    cached = _game_cache.get(category_id)
    if cached and cached[0] > now:
        return cached[1]

    url = "https://api.twitch.tv/helix/games"
    headers = {
        "Client-ID": CLIENT_ID,
        "Authorization": f"Bearer {await get_app_access_token()}",
    }
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(
            url,
            headers=headers,
            params={"id": category_id},
        ) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(
                    f"Twitch Helix /games returned HTTP {resp.status}: {body[:300]}"
                )
            payload = await resp.json()

    rows = payload.get("data") or []
    if not rows:
        _game_cache[category_id] = (now + 300, None)
        return None

    row = rows[0]
    result = {
        "id": str(row.get("id") or category_id),
        "name": str(row.get("name") or "").strip() or None,
        "igdb_id": str(row.get("igdb_id") or "").strip() or None,
        "box_art_url": str(row.get("box_art_url") or "").strip() or None,
    }
    _game_cache[category_id] = (now + 6 * 60 * 60, result)
    return result


async def get_app_access_token():
    now = time.time()
    cached = _app_token_cache.get("token")
    if cached and _app_token_cache.get("expires_at", 0.0) > now + 60:
        return cached

    url = "https://id.twitch.tv/oauth2/token"
    params = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "client_credentials",
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, params=params) as resp:
            data = await resp.json()

    token = data["access_token"]
    _app_token_cache["token"] = token
    _app_token_cache["expires_at"] = time.time() + int(data.get("expires_in", 4000000))
    return token
