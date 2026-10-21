"""Twitch OAuth Authorization Code flow helpers."""
from __future__ import annotations

from urllib.parse import urlencode

import aiohttp

from backend.config import get_backend_settings

TWITCH_AUTHORIZE_URL = "https://id.twitch.tv/oauth2/authorize"
TWITCH_TOKEN_URL = "https://id.twitch.tv/oauth2/token"
TWITCH_VALIDATE_URL = "https://id.twitch.tv/oauth2/validate"
TWITCH_USERS_URL = "https://api.twitch.tv/helix/users"


def build_authorize_url(state: str, scope: str | None = None) -> str:
    settings = get_backend_settings()
    params = {
        "client_id": settings.twitch_client_id or "",
        "redirect_uri": settings.twitch_redirect_uri or "",
        "response_type": "code",
        "scope": scope if scope is not None else settings.twitch_scope,
        "state": state,
    }
    return f"{TWITCH_AUTHORIZE_URL}?{urlencode(params)}"


async def exchange_code(code: str) -> dict:
    """Exchange a short lived Twitch authorization code for user tokens."""
    settings = get_backend_settings()
    if not settings.twitch_client_id or not settings.twitch_client_secret or not settings.twitch_redirect_uri:
        raise RuntimeError("Twitch OAuth is not configured")
    data = {
        "client_id": settings.twitch_client_id,
        "client_secret": settings.twitch_client_secret,
        "code": code,
        "grant_type": "authorization_code",
        "redirect_uri": settings.twitch_redirect_uri,
    }
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as client:
        async with client.post(TWITCH_TOKEN_URL, data=data) as response:
            body = await response.json(content_type=None)
            if response.status != 200:
                raise ValueError(body.get("message") or body.get("error") or "token exchange failed")
            return body


async def fetch_twitch_user(access_token: str) -> dict:
    """Return the Twitch user represented by an OAuth access token."""
    settings = get_backend_settings()
    if not settings.twitch_client_id:
        raise RuntimeError("Twitch OAuth is not configured")
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Client-Id": settings.twitch_client_id,
    }
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as client:
        async with client.get(TWITCH_USERS_URL, headers=headers) as response:
            body = await response.json(content_type=None)
            if response.status != 200:
                raise ValueError(body.get("message") or "unable to fetch Twitch user")
            users = body.get("data") or []
            if not users:
                raise ValueError("Twitch returned no user")
            return users[0]


async def refresh_access_token(refresh_token: str) -> dict:
    """Rotate a Twitch refresh token and return the new token payload."""
    settings = get_backend_settings()
    if not settings.twitch_client_id or not settings.twitch_client_secret:
        raise RuntimeError("Twitch OAuth is not configured")
    data = {
        "client_id": settings.twitch_client_id,
        "client_secret": settings.twitch_client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as client:
        async with client.post(TWITCH_TOKEN_URL, data=data) as response:
            body = await response.json(content_type=None)
            if response.status != 200:
                raise ValueError(body.get("message") or body.get("error") or "token refresh failed")
            if not body.get("access_token"):
                raise ValueError("Twitch returned no access token")
            return body
