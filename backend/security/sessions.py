"""Web session helpers (cookie-backed, stored in `web_sessions`)."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from fastapi import Response
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import WebSession
from backend.config import get_backend_settings


async def create_session(session: AsyncSession, user_id: int) -> WebSession:
    settings = get_backend_settings()
    now = datetime.utcnow()
    web_session = WebSession(
        id=uuid.uuid4(),
        user_id=user_id,
        created_at=now,
        last_activity_at=now,
        expires_at=now + timedelta(days=settings.backend_session_ttl_days),
    )
    session.add(web_session)
    await session.flush()
    return web_session


def attach_session_cookie(response: Response, web_session: WebSession) -> None:
    settings = get_backend_settings()
    response.set_cookie(
        key=settings.backend_cookie_name,
        value=str(web_session.id),
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


def attach_csrf_cookie(response: Response, token: str) -> None:
    settings = get_backend_settings()
    response.set_cookie(
        key=settings.backend_csrf_cookie_name,
        value=token,
        httponly=False,
        secure=settings.backend_cookie_secure,
        samesite="lax",
        max_age=settings.backend_session_ttl_days * 24 * 3600,
        path="/",
    )


def clear_csrf_cookie(response: Response) -> None:
    settings = get_backend_settings()
    response.delete_cookie(settings.backend_csrf_cookie_name, path="/")
