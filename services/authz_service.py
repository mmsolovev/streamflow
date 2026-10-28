"""Единая модель ролей, возможностей и ограничений.

Источник истины — `users.role`; env-списки используются только для первичного
seed. Этот модуль не должен импортировать FastAPI/twitchio, чтобы его могли
использовать и backend, и команды бота.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select
from sqlalchemy.exc import NoInspectionAvailable
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config.settings import OWNER_TWITCH_LOGIN, OWNER_TWITCH_USER_ID
from database.db import AsyncSessionLocal
from database.models import User, UserProfile, UserRestriction


class Role(str, Enum):
    OWNER = "owner"
    STREAMER = "streamer"
    ADMIN = "admin"
    EDITOR = "editor"
    USER = "user"


class Capability(str, Enum):
    RECOMMEND = "recommend"
    EDIT_TABLES = "edit_tables"
    ADMIN_COMMANDS = "admin_commands"
    MANAGE_EDITORS = "manage_editors"
    MANAGE_STAFF = "manage_staff"
    MANAGE_SERVICE_BAN = "manage_service_ban"


ROLE_RANK: dict[Role, int] = {
    Role.OWNER: 100,
    Role.STREAMER: 80,
    Role.ADMIN: 60,
    Role.EDITOR: 40,
    Role.USER: 20,
}

_ALL = frozenset(Capability)

ROLE_CAPABILITIES: dict[Role, frozenset[Capability]] = {
    Role.OWNER: _ALL,
    Role.STREAMER: _ALL - {Capability.MANAGE_STAFF, Capability.MANAGE_SERVICE_BAN},
    Role.ADMIN: frozenset(
        {
            Capability.RECOMMEND,
            Capability.EDIT_TABLES,
            Capability.ADMIN_COMMANDS,
            Capability.MANAGE_EDITORS,
        }
    ),
    Role.EDITOR: frozenset({Capability.RECOMMEND, Capability.EDIT_TABLES}),
    Role.USER: frozenset({Capability.RECOMMEND}),
}

# Для service-бана: любые изменения данных/ролей. Чтение не является capability.
WRITE_CAPABILITIES = frozenset(Capability)


@dataclass(frozen=True)
class Restrictions:
    twitch_banned: bool = False
    service_banned: bool = False


@dataclass(frozen=True)
class Actor:
    user_id: int | None
    role: Role
    restrictions: Restrictions = Restrictions()
    login: str | None = None
    display_name: str | None = None
    twitch_user_id: str | None = None

    @property
    def capabilities(self) -> list[str]:
        return sorted(cap.value for cap in ROLE_CAPABILITIES[self.role])

    @property
    def display_role(self) -> str:
        return display_role(self.role)

    @property
    def can_write(self) -> bool:
        # A Twitch ban only limits the regular user's recommendation action;
        # staff keep their role-derived capabilities.  Derive this from the
        # actual capability check so `/auth/me` cannot claim a blocked user
        # can still write.
        return any(can(self.role, capability, self.restrictions) for capability in WRITE_CAPABILITIES)

    def can(self, capability: Capability) -> bool:
        return can(self.role, capability, self.restrictions)

    def can_command(self, capability: Capability) -> bool:
        # Service bans only restrict web writes; bot commands keep their
        # role-derived access. Twitch bans still affect regular users.
        restrictions = Restrictions(twitch_banned=self.restrictions.twitch_banned)
        return can(self.role, capability, restrictions)


def coerce_role(value: str | Role | None) -> Role:
    if isinstance(value, Role):
        return value
    try:
        return Role((value or "").strip().casefold())
    except ValueError:
        return Role.USER


def role_at_least(role: Role | str, minimum: Role | str) -> bool:
    return ROLE_RANK[coerce_role(role)] >= ROLE_RANK[coerce_role(minimum)]


def display_role(role: Role | str) -> str:
    role = coerce_role(role)
    if role in {Role.OWNER, Role.STREAMER, Role.ADMIN}:
        return Role.ADMIN.value
    return role.value


def can(role: Role | str, capability: Capability, restrictions: Restrictions | None = None) -> bool:
    role = coerce_role(role)
    restrictions = restrictions or Restrictions()
    if role is Role.OWNER:
        return True
    if restrictions.service_banned:
        return False
    if role is Role.USER and restrictions.twitch_banned and capability is Capability.RECOMMEND:
        return False
    return capability in ROLE_CAPABILITIES[role]


def can_any(role: Role | str, capabilities: set[Capability], restrictions: Restrictions | None = None) -> bool:
    return any(can(role, capability, restrictions) for capability in capabilities)


def is_owner_identity(twitch_user_id: str | None, login: str | None) -> bool:
    owner_twitch_id = (OWNER_TWITCH_USER_ID or "").strip()
    owner_login = (OWNER_TWITCH_LOGIN or "").strip().casefold()
    if twitch_user_id and owner_twitch_id and str(twitch_user_id) == owner_twitch_id:
        return True
    return bool(login and owner_login and login.strip().casefold() == owner_login)


def restrictions_from_rows(rows: list[UserRestriction], now: datetime | None = None) -> Restrictions:
    now = now or datetime.utcnow()
    twitch_banned = False
    service_banned = False
    for row in rows:
        if row.lifted_at is not None:
            continue
        if row.expires_at is not None and row.expires_at <= now:
            continue
        if row.kind == "twitch_ban":
            twitch_banned = True
        elif row.kind == "service_ban":
            service_banned = True
    return Restrictions(twitch_banned=twitch_banned, service_banned=service_banned)


async def load_restrictions(session: AsyncSession, user_id: int) -> Restrictions:
    rows = (
        await session.execute(
            select(UserRestriction).where(
                UserRestriction.user_id == user_id,
                UserRestriction.lifted_at.is_(None),
            )
        )
    ).scalars().all()
    return restrictions_from_rows(list(rows))


def _loaded_current_profile(user: User):
    try:
        state = sa_inspect(user)
    except NoInspectionAvailable:
        return getattr(user, "current_profile", None)
    if "profiles" in state.unloaded:
        return None
    return user.current_profile


def actor_from_user(user: User, restrictions: Restrictions | None = None) -> Actor:
    profile = _loaded_current_profile(user)
    return Actor(
        user_id=user.id,
        role=coerce_role(getattr(user, "role", None)),
        restrictions=restrictions or Restrictions(),
        login=profile.login if profile else None,
        display_name=profile.display_name if profile else None,
        twitch_user_id=getattr(user, "twitch_user_id", None),
    )


async def get_actor(session: AsyncSession, user: User) -> Actor:
    restrictions = await load_restrictions(session, user.id)
    return actor_from_user(user, restrictions)


def apply_owner_bootstrap(user: User, login: str | None = None) -> bool:
    """Восстанавливает роль владельца по неизменяемому Twitch ID/логину."""
    profile_login = login
    if profile_login is None:
        profile = _loaded_current_profile(user)
        profile_login = profile.login if profile else None
    if not is_owner_identity(user.twitch_user_id, profile_login):
        return False
    if user.role != Role.OWNER.value:
        user.role = Role.OWNER.value
        return True
    return False


# --- Кэш для команд бота -------------------------------------------------

_CACHE_TTL_SECONDS = 60.0
_actor_cache: dict[str, tuple[float, Actor]] = {}


def _cache_key(twitch_user_id: str | None, login: str | None) -> str:
    return f"id:{twitch_user_id}" if twitch_user_id else f"login:{(login or '').casefold()}"


def invalidate_actor_cache() -> None:
    _actor_cache.clear()


async def resolve_actor(
    *,
    twitch_user_id: str | None = None,
    login: str | None = None,
    use_cache: bool = True,
) -> Actor:
    """Найти роль пользователя для команды бота (по Twitch ID, затем по логину)."""
    key = _cache_key(twitch_user_id, login)
    now = time.monotonic()
    if use_cache:
        cached = _actor_cache.get(key)
        if cached and cached[0] > now:
            return cached[1]

    async with AsyncSessionLocal() as session:
        user = None
        if twitch_user_id:
            user = (
                await session.execute(
                    select(User)
                    .where(User.twitch_user_id == str(twitch_user_id))
                    .options(selectinload(User.profiles))
                )
            ).scalar_one_or_none()
        if user is None and login:
            user = (
                await session.execute(
                    select(User)
                    .join(UserProfile, UserProfile.user_id == User.id)
                    .where(
                        UserProfile.login == login.strip().casefold(),
                        UserProfile.is_current.is_(True),
                    )
                    .options(selectinload(User.profiles))
                )
            ).scalar_one_or_none()
        if user is None:
            actor = Actor(user_id=None, role=Role.USER, login=login)
        else:
            restrictions = await load_restrictions(session, user.id)
            actor = actor_from_user(user, restrictions)

    _actor_cache[key] = (now + _CACHE_TTL_SECONDS, actor)
    return actor
