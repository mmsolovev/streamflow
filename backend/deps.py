"""FastAPI dependencies: session, current user and capability checks."""
from __future__ import annotations

from datetime import datetime, timedelta
import secrets
from typing import Annotated, AsyncGenerator, Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.db import AsyncSessionLocal
from database.models import User, WebSession
from backend.config import get_backend_settings
from backend.security.sessions import hash_secret
from services.authz_service import (
    Actor,
    Capability,
    actor_from_user,
    apply_owner_bootstrap,
    can,
    load_restrictions,
)
from services.streamer_service import resolve_primary_streamer_id


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_streamer_id(session: SessionDep) -> int:
    return await resolve_primary_streamer_id(session)


StreamerIdDep = Annotated[int, Depends(get_streamer_id)]


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "unauthorized", "message": "Требуется авторизация."},
    )


def _forbidden(message: str = "Недостаточно прав.", code: str = "forbidden") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"code": code, "message": message},
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

    token_hash = hash_secret(cookie_value)
    now = datetime.utcnow()
    web_session = (
        await session.execute(
            select(WebSession).where(WebSession.token_hash == token_hash)
        )
    ).scalar_one_or_none()
    if not web_session:
        raise _unauthorized()
    if web_session.expires_at <= now:
        await session.delete(web_session)
        await session.commit()
        raise _unauthorized()
    if web_session.absolute_expires_at and web_session.absolute_expires_at <= now:
        await session.delete(web_session)
        await session.commit()
        raise _unauthorized()

    user = await session.get(User, web_session.user_id, options=[selectinload(User.profiles)])
    if not user:
        raise _unauthorized()

    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        csrf_cookie = request.cookies.get(settings.backend_csrf_cookie_name)
        csrf_header = request.headers.get("X-CSRF-Token")
        if (
            not csrf_cookie
            or not csrf_header
            or not secrets.compare_digest(csrf_cookie, csrf_header)
            or not web_session.csrf_hash
            or not secrets.compare_digest(hash_secret(csrf_header), web_session.csrf_hash)
        ):
            raise _csrf_failed()

    if apply_owner_bootstrap(user):
        await session.flush()

    # Keep the cached Twitch restriction fresh on authenticated API access.
    # The service applies its own TTL and fails open when Twitch is unavailable.
    from services.twitch_ban_service import sync_user_twitch_ban

    await sync_user_twitch_ban(user.id, user.twitch_user_id)
    restrictions = await load_restrictions(session, user.id)
    request.state.actor = actor_from_user(user, restrictions)
    request.state.current_user = user

    web_session.last_activity_at = now
    idle_expires = now + timedelta(minutes=max(1, settings.backend_session_idle_minutes))
    if web_session.absolute_expires_at and idle_expires > web_session.absolute_expires_at:
        idle_expires = web_session.absolute_expires_at
    web_session.expires_at = idle_expires
    await session.commit()
    return user


async def get_current_user(
    session: SessionDep,
    request: Request,
) -> User:
    return await _resolve_user(session, request)


CurrentUserDep = Annotated[User, Depends(get_current_user)]


async def get_current_actor(request: Request, user: CurrentUserDep) -> Actor:
    actor = getattr(request.state, "actor", None)
    if actor is not None:
        return actor
    # Dependency overrides in tests (and custom auth adapters) may provide the
    # user without going through `_resolve_user`.
    return actor_from_user(user)


CurrentActorDep = Annotated[Actor, Depends(get_current_actor)]


def require_capability(capability: Capability) -> Callable[[Actor], Actor]:
    def _dependency(actor: CurrentActorDep) -> Actor:
        if not can(actor.role, capability, actor.restrictions):
            if actor.restrictions.service_banned:
                raise _forbidden("Действия ограничены для этого аккаунта.", "service_banned")
            if (
                actor.role.value == "user"
                and actor.restrictions.twitch_banned
                and capability is Capability.RECOMMEND
            ):
                raise _forbidden("Аккаунт забанен на канале стримера.", "twitch_banned")
            raise _forbidden()
        return actor

    return _dependency


def require_admin(actor: CurrentActorDep) -> Actor:
    if not can(actor.role, Capability.ADMIN_COMMANDS, actor.restrictions):
        raise _forbidden()
    return actor


AdminDep = Annotated[Actor, Depends(require_admin)]
EditorDep = Annotated[Actor, Depends(require_capability(Capability.EDIT_TABLES))]


def require_streamer_or_admin(actor: CurrentActorDep) -> Actor:
    if not can(actor.role, Capability.EDIT_TABLES, actor.restrictions):
        raise _forbidden()
    return actor


StreamerOrAdminDep = Annotated[Actor, Depends(require_streamer_or_admin)]


def current_user_login(user: User) -> tuple[str, str]:
    profile = user.current_profile
    login = (profile.login if profile and profile.login else None) or "unknown"
    display_name = (profile.display_name if profile and profile.display_name else None) or login
    return login, display_name
