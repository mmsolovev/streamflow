"""
Centralized user service: get-or-create from Chatter or login,
profile management (login/display_name can change on Twitch), and
background Twitch API enrichment for new users.

Identity is always resolved by the immutable twitch_user_id (falling back to
login for legacy rows), while mutable display data lives in user_profiles.
Nickname changes create a new current profile row without touching the User
row, so message/history joins anchored on users.id stay stable.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import aiohttp
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import CLIENT_ID, TWITCH_ACCESS_TOKEN
from database.models import User, UserProfile

logger = logging.getLogger(__name__)

TWITCH_API = "https://api.twitch.tv/helix"


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _twitch_url(login: str) -> str:
    return f"https://www.twitch.tv/{login}"


async def _find_user_identity(
    session: AsyncSession, *, twitch_user_id: str | None, login: str | None
) -> User | None:
    """Resolve a user by immutable twitch_user_id first, then current login.

    The login fallback covers legacy pipeline rows created before twitch_user_id
    was tracked; it matches the currently-active profile only.
    """
    if twitch_user_id:
        result = await session.execute(select(User).where(User.twitch_user_id == twitch_user_id))
        user = result.scalar_one_or_none()
        if user is not None:
            return user

    if login:
        result = await session.execute(
            select(User)
            .join(UserProfile, UserProfile.user_id == User.id)
            .where(UserProfile.login == login, UserProfile.is_current.is_(True))
        )
        return result.scalar_one_or_none()

    return None


async def _find_user_by_login_any_profile(session: AsyncSession, login: str) -> User | None:
    """Resolve a user by login across all profile rows (current or historical).

    Used by the pipeline path where only a login is known: a login that belongs
    to a historical nick should still map back to the same User row.
    """
    result = await session.execute(
        select(User)
        .join(UserProfile, UserProfile.user_id == User.id)
        .where(UserProfile.login == login)
    )
    return result.scalar_one_or_none()


async def find_user_by_login(session: AsyncSession, login: str) -> User | None:
    """Read-only lookup of a user by login (current or historical profile)."""
    return await _find_user_by_login_any_profile(session, login)


async def _ensure_current_profile(
    session: AsyncSession,
    user: User,
    *,
    login: str,
    display_name: str | None,
    now,
    twitch_user_id: str | None,
) -> UserProfile:
    """Keep a single current profile per user, tracking nickname changes.

    Same login -> refresh mutable fields in place.  Different login -> close
    the previous profile period (is_current=false) and open a new one.
    """
    if user.twitch_user_id is None and twitch_user_id:
        user.twitch_user_id = twitch_user_id

    result = await session.execute(
        select(UserProfile).where(UserProfile.user_id == user.id, UserProfile.is_current.is_(True))
    )
    profile = result.scalar_one_or_none()

    if profile is not None and profile.login == login:
        profile.login = login
        profile.display_name = display_name or profile.display_name
        profile.last_seen_at = now
        profile.updated_at = now
        return profile

    if profile is not None:
        profile.is_current = False
        profile.last_seen_at = now
        profile.updated_at = now

    new_profile = UserProfile(
        user_id=user.id,
        login=login,
        display_name=display_name or f"@{login}",
        twitch_url=_twitch_url(login),
        first_seen_at=now,
        last_seen_at=now,
        is_current=True,
        updated_at=now,
    )
    session.add(new_profile)
    await session.flush()
    return new_profile


async def get_or_create_user(session: AsyncSession, chatter) -> User:
    """Find or create a User from a twitchio Chatter object.

    Identity is resolved by twitch_user_id (chatter.id); legacy rows are found
    by the current login.  Mutable data (login/display_name) is tracked through
    user_profiles so renames keep message history on a single User row.  For
    newly created users a background task enriches the profile from Twitch API.
    """
    login = chatter.name
    display_name = getattr(chatter, "display_name", None) or login
    twitch_user_id = str(chatter.id) if getattr(chatter, "id", None) else None
    now = _utcnow()

    user = await _find_user_identity(
        session, twitch_user_id=twitch_user_id, login=login or None
    )
    if user is not None:
        await _ensure_current_profile(
            session,
            user,
            login=login,
            display_name=display_name,
            now=now,
            twitch_user_id=twitch_user_id,
        )
        return user

    # No match: create a new identity inside a savepoint so a concurrent insert
    # of the same twitch_user_id falls back to the existing row.
    try:
        async with session.begin_nested():
            user = User(
                twitch_user_id=twitch_user_id,
                is_streamer=getattr(chatter, "broadcaster", False),
                created_at=now,
            )
            session.add(user)
            await session.flush()
            session.add(
                UserProfile(
                    user_id=user.id,
                    login=login,
                    display_name=display_name,
                    twitch_url=_twitch_url(login),
                    first_seen_at=now,
                    last_seen_at=now,
                    is_current=True,
                    updated_at=now,
                )
            )
            await session.flush()
    except IntegrityError:
        user = await _find_user_identity(
            session, twitch_user_id=twitch_user_id, login=login or None
        )
        if user is None:
            raise
        await _ensure_current_profile(
            session,
            user,
            login=login,
            display_name=display_name,
            now=now,
            twitch_user_id=twitch_user_id,
        )
        return user

    if twitch_user_id:
        asyncio.create_task(_enrich_user_from_twitch(twitch_user_id))

    return user


async def get_or_create_user_by_twitch_id(
    session: AsyncSession, *, twitch_user_id: str, login: str, display_name: str | None
) -> User:
    """Create or refresh a user from stable Twitch identity data.

    Used by non-Chatter paths (clips, API responses) that know the immutable
    twitch_user_id plus the current login/display_name.
    """
    now = _utcnow()
    user = await _find_user_identity(
        session, twitch_user_id=twitch_user_id, login=login or None
    )
    if user is not None:
        await _ensure_current_profile(
            session,
            user,
            login=login,
            display_name=display_name,
            now=now,
            twitch_user_id=twitch_user_id,
        )
        return user

    try:
        async with session.begin_nested():
            user = User(twitch_user_id=twitch_user_id, created_at=now)
            session.add(user)
            await session.flush()
            session.add(
                UserProfile(
                    user_id=user.id,
                    login=login,
                    display_name=display_name or f"@{login}",
                    twitch_url=_twitch_url(login),
                    first_seen_at=now,
                    last_seen_at=now,
                    is_current=True,
                    updated_at=now,
                )
            )
            await session.flush()
    except IntegrityError:
        user = await _find_user_identity(
            session, twitch_user_id=twitch_user_id, login=login or None
        )
        if user is None:
            raise
        await _ensure_current_profile(
            session,
            user,
            login=login,
            display_name=display_name,
            now=now,
            twitch_user_id=twitch_user_id,
        )
        return user

    return user


async def get_or_create_user_by_login(session: AsyncSession, login: str) -> User:
    """Find or create a User by login name (pipeline / no Chatter context).

    Matches the login across any profile row (historical included) so a renamed
    user is not split into a second identity.
    """
    user = await _find_user_by_login_any_profile(session, login)
    if user is not None:
        return user

    now = _utcnow()
    user = User(created_at=now)
    session.add(user)
    await session.flush()
    session.add(
        UserProfile(
            user_id=user.id,
            login=login,
            display_name=f"@{login}",
            twitch_url=_twitch_url(login),
            first_seen_at=now,
            last_seen_at=now,
            is_current=True,
            updated_at=now,
        )
    )
    await session.flush()
    return user


async def get_or_create_users_bulk(
    session: AsyncSession,
    identities: list[tuple[str | None, str, str | None]],
) -> dict[str, User]:
    """Bulk resolve users for chat logging.

    `identities` — `(twitch_user_id, login, display_name)`. Возвращает словарь
    `key -> User`, где key — `twitch_user_id`, если он есть, иначе login.
    HTTP-обогащение не запускается: в чате это лишние запросы к Twitch.

    Никнейм меняется по тем же правилам, что и в `_ensure_current_profile`:
    старый профиль закрывается, открывается новый текущий.
    """
    now = _utcnow()
    normalized: list[tuple[str, str | None, str, str | None]] = []
    for twitch_user_id, login, display_name in identities:
        twitch_user_id = str(twitch_user_id) if twitch_user_id else None
        login = (login or "").strip()
        if not login and not twitch_user_id:
            continue
        normalized.append((twitch_user_id or login, twitch_user_id, login, display_name))

    ids = {item[1] for item in normalized if item[1]}
    logins = {item[2] for item in normalized if item[2]}

    users_by_id: dict[str, User] = {}
    if ids:
        rows = await session.execute(select(User).where(User.twitch_user_id.in_(ids)))
        users_by_id = {
            str(user.twitch_user_id): user
            for user in rows.scalars().all()
            if user.twitch_user_id
        }

    users_by_login: dict[str, User] = {}
    if logins:
        rows = await session.execute(
            select(UserProfile.login, User)
            .join(User, User.id == UserProfile.user_id)
            .where(UserProfile.login.in_(logins), UserProfile.is_current.is_(True))
        )
        users_by_login = {login: user for login, user in rows.all()}

    resolved_ids = {
        int(user.id)
        for user in list(users_by_id.values()) + list(users_by_login.values())
        if user.id is not None
    }
    profiles_by_user: dict[int, UserProfile] = {}
    if resolved_ids:
        rows = await session.execute(
            select(UserProfile).where(
                UserProfile.user_id.in_(resolved_ids),
                UserProfile.is_current.is_(True),
            )
        )
        profiles_by_user = {int(profile.user_id): profile for profile in rows.scalars().all()}

    result: dict[str, User] = {}
    new_profiles: dict[str, tuple[User, str, str | None]] = {}

    for key, twitch_user_id, login, display_name in normalized:
        user = users_by_id.get(twitch_user_id) if twitch_user_id else None
        if user is None and login:
            user = users_by_login.get(login)

        if user is None:
            user = User(twitch_user_id=twitch_user_id, created_at=now)
            session.add(user)
            users_by_id[twitch_user_id or login] = user
            if login:
                new_profiles[key] = (user, login, display_name)
            result[key] = user
            continue

        if user.twitch_user_id is None and twitch_user_id:
            user.twitch_user_id = twitch_user_id

        profile = profiles_by_user.get(int(user.id))
        if profile is not None and profile.login == login:
            profile.display_name = display_name or profile.display_name
            profile.last_seen_at = now
            profile.updated_at = now
        else:
            if profile is not None:
                profile.is_current = False
                profile.last_seen_at = now
                profile.updated_at = now
            if login:
                new_profiles[key] = (user, login, display_name)

        result[key] = user

    if new_profiles:
        await session.flush()  # ids новых User
        for user, login, display_name in new_profiles.values():
            session.add(
                UserProfile(
                    user_id=user.id,
                    login=login,
                    display_name=display_name or f"@{login}",
                    twitch_url=_twitch_url(login),
                    first_seen_at=now,
                    last_seen_at=now,
                    is_current=True,
                    updated_at=now,
                )
            )

    await session.flush()
    return result


async def _enrich_user_from_twitch(twitch_user_id: str) -> None:
    """Background task: fetch full profile from Twitch API and update DB.

    Looks the user up by the immutable twitch_user_id (from the API response),
    so enrichment survives a nickname change done between enqueue and request.
    """
    await asyncio.sleep(1)

    if not CLIENT_ID or not TWITCH_ACCESS_TOKEN:
        return

    try:
        headers = {
            "Client-ID": CLIENT_ID,
            "Authorization": f"Bearer {TWITCH_ACCESS_TOKEN}",
        }
        async with aiohttp.ClientSession() as http:
            async with http.get(
                f"{TWITCH_API}/users",
                headers=headers,
                params={"id": twitch_user_id},
            ) as resp:
                if resp.status != 200:
                    logger.debug(
                        "Twitch API /users returned %s for %s", resp.status, twitch_user_id
                    )
                    return
                data = await resp.json()

        rows = data.get("data") or []
        if not rows:
            return

        row = rows[0]
        api_user_id = str(row.get("id"))
        login = (row.get("login") or "").strip()
        display_name = row.get("display_name")

        from database.db import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            user = await _find_user_identity(
                session, twitch_user_id=api_user_id, login=login or None
            )
            if user is None:
                return

            await _ensure_current_profile(
                session,
                user,
                login=login,
                display_name=display_name,
                now=_utcnow(),
                twitch_user_id=api_user_id,
            )

            result = await session.execute(
                select(UserProfile).where(
                    UserProfile.user_id == user.id, UserProfile.is_current.is_(True)
                )
            )
            profile = result.scalar_one_or_none()
            if profile is not None:
                profile.profile_image_url = row.get("profile_image_url")
                profile.updated_at = _utcnow()

            await session.commit()
    except Exception as exc:
        logger.warning("Twitch API enrichment failed for %s: %s", twitch_user_id, exc)