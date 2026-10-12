"""FastAPI dependencies: session and auth placeholders."""
from __future__ import annotations

from datetime import datetime
import secrets
from typing import Annotated, AsyncGenerator
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config.settings import SHEETS_STREAMER_ID
from database.db import AsyncSessionLocal
from database.models import User, WebSession
from backend.config import get_backend_settings


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_streamer_id() -> int:
    settings = get_backend_settings()
    return settings.backend_streamer_id if settings.backend_streamer_id is not None else SHEETS_STREAMER_ID


StreamerIdDep = Annotated[int, Depends(get_streamer_id)]


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "unauthorized", "message": "Требуется авторизация."},
    )


def _forbidden() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": "forbidden", "message": "Недостаточно прав."},
    )


def _csrf_failed() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": "csrf_failed", "message": "Некорректный CSRF-токен."},
    )


async def _resolve_user(session: AsyncSession, request: Request) -> User:
    settings = get_backend_settings()
    cookie_value = request.cookies.get(settings.backend_cookie_name)
    if not cookie_value:
        raise _unauthorized()

    try:
        session_id = UUID(cookie_value)
    except (ValueError, AttributeError, TypeError):
        raise _unauthorized()

    now = datetime.utcnow()
    result = await session.execute(
        select(WebSession).where(WebSession.id == session_id, WebSession.expires_at > now)
    )
    web_session = result.scalar_one_or_none()
    if not web_session:
        raise _unauthorized()

    user = await session.get(User, web_session.user_id, options=[selectinload(User.profiles)])
    if not user:
        raise _unauthorized()
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        csrf_cookie = request.cookies.get(settings.backend_csrf_cookie_name)
        csrf_header = request.headers.get("X-CSRF-Token")
        if not csrf_cookie or not csrf_header or not secrets.compare_digest(csrf_cookie, csrf_header):
            raise _csrf_failed()
    web_session.last_activity_at = now
    await session.commit()
    return user


async def get_current_user(
    session: SessionDep,
    request: Request,
) -> User:
    return await _resolve_user(session, request)


CurrentUserDep = Annotated[User, Depends(get_current_user)]


def require_streamer_or_admin(user: CurrentUserDep) -> User:
    if not (user.is_streamer or user.is_admin):
        raise _forbidden()
    return user


StreamerOrAdminDep = Annotated[User, Depends(require_streamer_or_admin)]


def require_admin(user: CurrentUserDep) -> User:
    if not user.is_admin:
        raise _forbidden()
    return user


AdminDep = Annotated[User, Depends(require_admin)]


def current_user_login(user: User) -> tuple[str, str]:
    profile = user.current_profile
    login = (profile.login if profile and profile.login else None) or "unknown"
    display_name = (profile.display_name if profile and profile.display_name else None) or login
    return login, display_name
