"""Web session helpers (cookie-backed, stored in `web_sessions`)."""
from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from fastapi import Response
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import WebSession
from backend.config import get_backend_settings


SESSION_TOKEN_BYTES = 32


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class IssuedSession:
    web_session: WebSession
    token: str
    csrf_token: str


async def create_session(session: AsyncSession, user_id: int) -> IssuedSession:
    settings = get_backend_settings()
    now = datetime.utcnow()
    token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
    csrf_token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
    idle_delta = timedelta(minutes=max(1, settings.backend_session_idle_minutes))
    absolute_delta = timedelta(days=max(1, settings.backend_session_ttl_days))
    web_session = WebSession(
        id=uuid.uuid4(),
        user_id=user_id,
        token_hash=hash_secret(token),
        csrf_hash=hash_secret(csrf_token),
        created_at=now,
        last_activity_at=now,
        expires_at=now + idle_delta,
        absolute_expires_at=now + absolute_delta,
    )
    session.add(web_session)
    await session.flush()
    return IssuedSession(web_session=web_session, token=token, csrf_token=csrf_token)


def attach_session_cookie(response: Response, issued: IssuedSession) -> None:
    settings = get_backend_settings()
    response.set_cookie(
        key=settings.backend_cookie_name,
        value=issued.token,
        httponly=True,
        secure=settings.backend_cookie_secure,
        samesite="lax",
        max_age=settings.backend_session_ttl_days * 24 * 3600,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    settings = get_backend_settings()
    response.delete_cookie(settings.backend_cookie_name, path="/")


def attach_oauth_state_cookie(response: Response, state: str) -> None:
    settings = get_backend_settings()
    response.set_cookie(
        key=settings.backend_oauth_state_cookie_name,
        value=state,
        httponly=True,
        secure=settings.backend_cookie_secure,
        samesite="lax",
        max_age=settings.twitch_oauth_state_ttl_seconds,
        path="/",
    )


def clear_oauth_state_cookie(response: Response) -> None:
    settings = get_backend_settings()
    response.delete_cookie(settings.backend_oauth_state_cookie_name, path="/")


def attach_csrf_cookie(response: Response, issued: IssuedSession) -> None:
    settings = get_backend_settings()
    response.set_cookie(
        key=settings.backend_csrf_cookie_name,
        value=issued.csrf_token,
        httponly=False,
        secure=settings.backend_cookie_secure,
        samesite="lax",
        max_age=settings.backend_session_ttl_days * 24 * 3600,
        path="/",
    )


def clear_csrf_cookie(response: Response) -> None:
    settings = get_backend_settings()
    response.delete_cookie(settings.backend_csrf_cookie_name, path="/")
