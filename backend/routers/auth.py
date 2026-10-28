"""Twitch OAuth login and cookie-backed web sessions."""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config.settings import STREAMER_LOGINS
from database.models import (
    TwitchAuthorization,
    TwitchStreamerAuthorization,
    User,
    UserProfile,
    WebSession,
)
from backend.config import get_backend_settings
from backend.deps import (
    AdminDep,
    CurrentActorDep,
    CurrentUserDep,
    SessionDep,
    current_user_login,
)
from backend.schemas.auth import StreamerAuthStatus, StreamerAuthorizationView, UserView
from backend.security.sessions import (
    attach_oauth_state_cookie,
    attach_csrf_cookie,
    attach_session_cookie,
    clear_csrf_cookie,
    clear_oauth_state_cookie,
    clear_session_cookie,
    create_session,
    hash_secret,
)
from backend.security.token_crypto import (
    KEY_VERSION,
    decrypt_stored_token,
    encrypt_token,
)
from backend.security.twitch_oauth import build_authorize_url, exchange_code, fetch_twitch_user
from services.authz_service import (
    Actor,
    Role,
    actor_from_user,
    apply_owner_bootstrap,
    coerce_role,
    display_role,
)

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


def _user_view(user: User, login: str, display_name: str, actor: Actor | None = None) -> UserView:
    role = actor.role if actor else coerce_role(user.role)
    restrictions = actor.restrictions if actor else None
    return UserView(
        id=user.id,
        login=login if login != "unknown" else None,
        display_name=display_name if display_name != "unknown" else None,
        role=role.value,
        display_role=display_role(role),
        capabilities=actor.capabilities if actor else [],
        is_twitch_banned=bool(restrictions and restrictions.twitch_banned),
        is_service_banned=bool(restrictions and restrictions.service_banned),
        can_write=actor.can_write if actor else False,
        # Переходные поля: фронтенд должен использовать role/capabilities.
        is_streamer=role is Role.STREAMER,
        is_admin=role in {Role.OWNER, Role.STREAMER, Role.ADMIN},
    )


def _oauth_error(message: str, code: str = "oauth_error") -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={"code": code, "message": message},
    )


def _frontend_redirect_with(base: str, **params: str) -> str:
    parts = urlsplit(base)
    query = dict(parse_qsl(parts.query))
    query.update(params)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def _new_oauth_state(flow: str) -> str:
    """OAuth-state c префиксом флоу: `login.<random>` или `streamer.<random>`.

    Оба входа (обычный и стримерский) используют один и тот же redirect_uri,
    поэтому различаем поток по префиксу state, а не второй регистрацией URL.
    """
    return f"{flow}.{secrets.token_urlsafe(32)}"


def _oauth_state_flow(value: str | None) -> str | None:
    if not value or "." not in value:
        return None
    flow = value.split(".", 1)[0]
    return flow if flow in {"login", "streamer"} else None


def _scopes_string(scopes: object) -> str:
    if isinstance(scopes, str):
        return scopes
    if isinstance(scopes, (list, tuple)):
        return " ".join(str(scope) for scope in scopes)
    return ""


async def _upsert_twitch_user(session: AsyncSession, twitch_user: dict) -> tuple[User, str, str]:
    """Создать/обновить `User` и текущий `UserProfile`. Возвращает (user, login, display_name)."""
    twitch_id = str(twitch_user.get("id") or "").strip()
    login = str(twitch_user.get("login") or "").strip().casefold()
    display_name = str(twitch_user.get("display_name") or login).strip()
    if not twitch_id or not login:
        raise _oauth_error("Twitch returned an incomplete user profile.", "invalid_twitch_user")

    now = datetime.utcnow()
    streamer_logins = {item.casefold() for item in STREAMER_LOGINS}
    user = (
        await session.execute(
            select(User)
            .where(User.twitch_user_id == twitch_id)
            .options(selectinload(User.profiles))
        )
    ).scalar_one_or_none()
    if user is None:
        user = User(
            twitch_user_id=twitch_id,
            created_at=now,
            role=Role.USER.value,
            is_streamer=login in streamer_logins,
        )
        session.add(user)
        await session.flush()

    # is_streamer — только Twitch-аффилиация (partner/affiliate), не staff-роль.
    if login in streamer_logins:
        user.is_streamer = True

    profile = (
        await session.execute(
            select(UserProfile).where(UserProfile.user_id == user.id, UserProfile.is_current.is_(True))
        )
    ).scalar_one_or_none()
    if profile is None:
        profile = UserProfile(user_id=user.id, is_current=True, first_seen_at=now)
        session.add(profile)
    profile.login = login
    profile.display_name = display_name
    profile.profile_image_url = twitch_user.get("profile_image_url")
    profile.twitch_url = f"https://twitch.tv/{login}"
    profile.last_seen_at = now
    profile.updated_at = now
    apply_owner_bootstrap(user, login)
    return user, login, display_name


async def _store_login_authorization(session: AsyncSession, user: User, token_data: dict) -> None:
    """Сохранить/обновить токен обычного веб-логина (таблица `twitch_authorizations`)."""
    now = datetime.utcnow()
    expires_in = token_data.get("expires_in")
    expires_at = now + timedelta(seconds=int(expires_in)) if expires_in else None
    authorization = await session.get(TwitchAuthorization, user.id)
    if authorization is None:
        authorization = TwitchAuthorization(user_id=user.id, created_at=now)
        session.add(authorization)
    refresh_token = token_data.get("refresh_token") or decrypt_stored_token(
        authorization.refresh_token_encrypted
    )
    if not refresh_token:
        raise ValueError("Twitch did not return a refresh token")
    authorization.access_token_encrypted = encrypt_token(token_data["access_token"])
    authorization.refresh_token_encrypted = encrypt_token(refresh_token)
    authorization.key_version = KEY_VERSION
    authorization.scopes = _scopes_string(token_data.get("scope") or [])
    authorization.expires_at = expires_at
    authorization.last_refresh_at = now
    authorization.updated_at = now


async def _store_streamer_authorization(
    session: AsyncSession, user: User, login: str, token_data: dict
) -> None:
    """Сохранить/обновить «стримерский» токен (таблица `twitch_streamer_authorizations`)."""
    now = datetime.utcnow()
    expires_in = token_data.get("expires_in")
    expires_at = now + timedelta(seconds=int(expires_in)) if expires_in else None
    authorization = await session.get(TwitchStreamerAuthorization, user.id)
    if authorization is None:
        authorization = TwitchStreamerAuthorization(user_id=user.id, created_at=now)
        session.add(authorization)
    authorization.twitch_login = login
    refresh_token = token_data.get("refresh_token") or decrypt_stored_token(
        authorization.refresh_token_encrypted
    )
    if not refresh_token:
        raise ValueError("Twitch did not return a refresh token")
    authorization.access_token_encrypted = encrypt_token(token_data["access_token"])
    authorization.refresh_token_encrypted = encrypt_token(refresh_token)
    authorization.key_version = KEY_VERSION
    authorization.scopes = _scopes_string(token_data.get("scope") or [])
    authorization.expires_at = expires_at
    authorization.last_refresh_at = now
    authorization.updated_at = now


@router.get("/me", response_model=UserView)
async def me(user: CurrentUserDep, actor: CurrentActorDep) -> UserView:
    login, display_name = current_user_login(user)
    return _user_view(user, login, display_name, actor)


@router.get("/login", response_class=RedirectResponse, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
async def login() -> Response:
    settings = get_backend_settings()
    if not settings.twitch_client_id or not settings.twitch_client_secret or not settings.twitch_redirect_uri:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "oauth_not_configured", "message": "Twitch OAuth is not configured."},
        )
    state = _new_oauth_state("login")
    redirect = RedirectResponse(build_authorize_url(state), status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    attach_oauth_state_cookie(redirect, state)
    return redirect


@router.get(
    "/streamer/login",
    response_class=RedirectResponse,
    status_code=status.HTTP_307_TEMPORARY_REDIRECT,
)
async def streamer_login() -> Response:
    """Вход стримера: тот же redirect_uri, но с расширенным набором scopes.

    Завершается на общем `/auth/callback` (поток определяется префиксом state).
    """
    settings = get_backend_settings()
    if not settings.twitch_client_id or not settings.twitch_client_secret or not settings.twitch_redirect_uri:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "oauth_not_configured", "message": "Twitch OAuth is not configured."},
        )
    state = _new_oauth_state("streamer")
    scope = " ".join(settings.twitch_streamer_scopes)
    redirect = RedirectResponse(
        build_authorize_url(state, scope=scope),
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )
    attach_oauth_state_cookie(redirect, state)
    return redirect


@router.get("/callback", response_model=UserView)
async def callback(
    request: Request,
    response: Response,
    session: SessionDep,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> UserView | Response:
    settings = get_backend_settings()
    oauth_state = request.cookies.get(settings.backend_oauth_state_cookie_name)
    if error:
        raise _oauth_error(f"Twitch authorization failed: {error}.")
    if not code or not state or not oauth_state or not secrets.compare_digest(state, oauth_state):
        raise _oauth_error("Invalid OAuth state.", "invalid_oauth_state")

    flow = _oauth_state_flow(state) or "login"

    try:
        token_data = await exchange_code(code)
        twitch_user = await fetch_twitch_user(token_data["access_token"])
        user, login_name, display_name = await _upsert_twitch_user(session, twitch_user)

        if flow == "streamer":
            allowed = {item.casefold() for item in STREAMER_LOGINS}
            role = coerce_role(user.role)
            if (
                login_name.casefold() not in allowed
                and role not in {Role.OWNER, Role.STREAMER}
            ):
                await session.rollback()
                if settings.backend_frontend_url:
                    response = RedirectResponse(
                        _frontend_redirect_with(settings.backend_frontend_url, streamer="denied"),
                        status_code=status.HTTP_303_SEE_OTHER,
                    )
                    clear_oauth_state_cookie(response)
                    return response
                raise _oauth_error(
                    "Этот аккаунт не имеет доступа к расширенным правам стримера.",
                    "streamer_not_allowed",
                )
            await _store_streamer_authorization(session, user, login_name, token_data)
            await session.commit()
            if settings.backend_frontend_url:
                redirect = RedirectResponse(
                    _frontend_redirect_with(settings.backend_frontend_url, streamer="success"),
                    status_code=status.HTTP_303_SEE_OTHER,
                )
                clear_oauth_state_cookie(redirect)
                return redirect
            return _user_view(user, login_name, display_name, actor_from_user(user))

        await _store_login_authorization(session, user, token_data)
        issued_session = await create_session(session, user.id)
        await session.commit()
        from services.twitch_ban_service import sync_user_twitch_ban

        await sync_user_twitch_ban(user.id, user.twitch_user_id, force=True)
    except HTTPException:
        await session.rollback()
        raise
    except (KeyError, ValueError) as exc:
        await session.rollback()
        raise _oauth_error(str(exc)) from exc
    except Exception as exc:
        await session.rollback()
        if isinstance(exc, RuntimeError) and str(exc) == "Twitch OAuth is not configured":
            raise _oauth_error(str(exc), "oauth_not_configured") from exc
        logger.exception("Twitch OAuth callback failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "oauth_provider_error", "message": "Twitch OAuth provider is unavailable."},
        ) from exc

    if settings.backend_frontend_url:
        redirect = RedirectResponse(
            _frontend_redirect_with(settings.backend_frontend_url, login="success"),
            status_code=status.HTTP_303_SEE_OTHER,
        )
        attach_session_cookie(redirect, issued_session)
        attach_csrf_cookie(redirect, issued_session)
        clear_oauth_state_cookie(redirect)
        return redirect

    attach_session_cookie(response, issued_session)
    attach_csrf_cookie(response, issued_session)
    clear_oauth_state_cookie(response)
    return _user_view(user, login_name, display_name, actor_from_user(user))


@router.get("/streamer/status", response_model=StreamerAuthStatus)
async def streamer_status(session: SessionDep, _admin: AdminDep) -> StreamerAuthStatus:
    """Статус «стримерских» токенов (только для админов).

    Показывает запрашиваемые scopes и по каждому логину из STREAMER_LOGINS —
    подключён ли расширенный токен.
    """
    settings = get_backend_settings()
    rows = (await session.execute(select(TwitchStreamerAuthorization))).scalars().all()
    by_login = {row.twitch_login.casefold(): row for row in rows}
    streamers = [
        StreamerAuthorizationView(
            login=login,
            connected=(row := by_login.get(login.casefold())) is not None,
            scopes=row.scopes if row else None,
            expires_at=row.expires_at if row else None,
        )
        for login in STREAMER_LOGINS
    ]
    return StreamerAuthStatus(
        requested_scopes=settings.twitch_streamer_scopes,
        streamers=streamers,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    session: SessionDep,
    _user: CurrentUserDep,
) -> Response:
    settings = get_backend_settings()
    cookie_value = request.cookies.get(settings.backend_cookie_name)
    if cookie_value:
        web_session = (
            await session.execute(
                select(WebSession).where(WebSession.token_hash == hash_secret(cookie_value))
            )
        ).scalar_one_or_none()
        if web_session:
            await session.delete(web_session)
            await session.commit()
    clear_session_cookie(response)
    clear_csrf_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response
