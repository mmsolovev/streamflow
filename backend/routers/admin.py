"""Role, service-ban and audit administration."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import delete, func, or_, select

from backend.deps import SessionDep, require_capability
from backend.schemas.admin import (
    AdminUserPage,
    AdminUserView,
    AuditPage,
    AuditView,
    RestrictionView,
    RoleChangeBody,
    ServiceBanBody,
)
from database.models import ModerationAudit, User, UserProfile, UserRestriction, WebSession
from services.authz_service import (
    Actor,
    Capability,
    Role,
    coerce_role,
    display_role,
    invalidate_actor_cache,
)

router = APIRouter(prefix="/admin", tags=["admin"])

ManageEditorsDep = Annotated[Actor, Depends(require_capability(Capability.MANAGE_EDITORS))]
ManageServiceBanDep = Annotated[
    Actor, Depends(require_capability(Capability.MANAGE_SERVICE_BAN))
]


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _restriction_view(row: UserRestriction) -> RestrictionView:
    return RestrictionView(
        id=row.id,
        kind=row.kind,
        channel=row.channel,
        reason=row.reason,
        source=row.source,
        expires_at=row.expires_at,
        created_at=row.created_at,
        created_by_user_id=row.created_by_user_id,
    )


def _user_view(
    user: User,
    profile: UserProfile | None,
    restrictions: list[UserRestriction],
) -> AdminUserView:
    now = datetime.utcnow()
    active = [
        row
        for row in restrictions
        if row.lifted_at is None and (row.expires_at is None or row.expires_at > now)
    ]
    role = coerce_role(user.role)
    return AdminUserView(
        id=user.id,
        login=profile.login if profile else None,
        display_name=(profile.display_name or profile.login) if profile else None,
        role=role.value,
        display_role=display_role(role),
        is_twitch_banned=any(row.kind == "twitch_ban" for row in active),
        is_service_banned=any(row.kind == "service_ban" for row in active),
        restrictions=[_restriction_view(row) for row in active],
        created_at=user.created_at,
    )


def _audit(
    session: SessionDep,
    request: Request,
    actor: Actor,
    target_user_id: int,
    action: str,
    *,
    old_value: str | None = None,
    new_value: str | None = None,
    reason: str | None = None,
) -> None:
    session.add(
        ModerationAudit(
            actor_user_id=actor.user_id,
            target_user_id=target_user_id,
            action=action,
            old_value=old_value,
            new_value=new_value,
            reason=reason,
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            created_at=datetime.utcnow(),
        )
    )


async def _revoke_sessions(session: SessionDep, user_id: int) -> None:
    await session.execute(delete(WebSession).where(WebSession.user_id == user_id))


@router.get("/users", response_model=AdminUserPage)
async def list_users(
    session: SessionDep,
    _actor: ManageEditorsDep,
    q: str | None = Query(None, max_length=64),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> AdminUserPage:
    stmt = (
        select(User, UserProfile)
        .outerjoin(
            UserProfile,
            (UserProfile.user_id == User.id) & (UserProfile.is_current.is_(True)),
        )
    )
    count_stmt = select(func.count(User.id))
    if q:
        term = f"%{q.strip().casefold()}%"
        condition = or_(
            func.lower(UserProfile.login).like(term),
            func.lower(UserProfile.display_name).like(term),
            User.twitch_user_id == q.strip(),
        )
        stmt = stmt.where(condition)
        count_stmt = count_stmt.join(
            UserProfile,
            (UserProfile.user_id == User.id) & (UserProfile.is_current.is_(True)),
        ).where(condition)

    total = (await session.execute(count_stmt)).scalar_one()
    rows = (
        await session.execute(
            stmt.order_by(func.lower(UserProfile.login).nullslast(), User.id)
            .offset(offset)
            .limit(limit)
        )
    ).all()
    user_ids = [user.id for user, _ in rows]
    restriction_map: dict[int, list[UserRestriction]] = {}
    if user_ids:
        restriction_rows = (
            await session.execute(
                select(UserRestriction).where(UserRestriction.user_id.in_(user_ids))
            )
        ).scalars().all()
        for row in restriction_rows:
            restriction_map.setdefault(row.user_id, []).append(row)

    return AdminUserPage(
        items=[
            _user_view(user, profile, restriction_map.get(user.id, []))
            for user, profile in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.patch("/users/{user_id}/role", response_model=AdminUserView)
async def change_role(
    user_id: int,
    body: RoleChangeBody,
    request: Request,
    session: SessionDep,
    actor: ManageEditorsDep,
) -> AdminUserView:
    target = await session.get(User, user_id)
    if target is None:
        raise _error(status.HTTP_404_NOT_FOUND, "not_found", "Пользователь не найден.")

    old_role = coerce_role(target.role)
    new_role = coerce_role(body.role)
    if old_role is Role.OWNER:
        raise _error(status.HTTP_403_FORBIDDEN, "owner_protected", "Роль владельца изменить нельзя.")
    if actor.role is not Role.OWNER:
        if new_role not in {Role.EDITOR, Role.USER} or old_role in {
            Role.ADMIN,
            Role.STREAMER,
            Role.OWNER,
        }:
            raise _error(
                status.HTTP_403_FORBIDDEN,
                "forbidden",
                "Стример и админ могут менять только роли редакторов.",
            )
    if new_role is old_role:
        profile = (
            await session.execute(
                select(UserProfile).where(
                    UserProfile.user_id == target.id,
                    UserProfile.is_current.is_(True),
                )
            )
        ).scalar_one_or_none()
        restrictions = (
            await session.execute(
                select(UserRestriction).where(UserRestriction.user_id == target.id)
            )
        ).scalars().all()
        return _user_view(target, profile, list(restrictions))

    target.role = new_role.value
    await _revoke_sessions(session, target.id)
    _audit(
        session,
        request,
        actor,
        target.id,
        "role_changed",
        old_value=old_role.value,
        new_value=new_role.value,
        reason=body.reason,
    )
    await session.commit()
    invalidate_actor_cache()

    profile = (
        await session.execute(
            select(UserProfile).where(
                UserProfile.user_id == target.id,
                UserProfile.is_current.is_(True),
            )
        )
    ).scalar_one_or_none()
    restrictions = (
        await session.execute(
            select(UserRestriction).where(UserRestriction.user_id == target.id)
        )
    ).scalars().all()
    return _user_view(target, profile, list(restrictions))


@router.post("/users/{user_id}/restrictions", response_model=RestrictionView, status_code=201)
async def create_service_ban(
    user_id: int,
    body: ServiceBanBody,
    request: Request,
    session: SessionDep,
    actor: ManageServiceBanDep,
) -> RestrictionView:
    target = await session.get(User, user_id)
    if target is None:
        raise _error(status.HTTP_404_NOT_FOUND, "not_found", "Пользователь не найден.")
    if coerce_role(target.role) is Role.OWNER:
        raise _error(status.HTTP_403_FORBIDDEN, "owner_protected", "Владельца нельзя заблокировать.")

    active = (
        await session.execute(
            select(UserRestriction).where(
                UserRestriction.user_id == target.id,
                UserRestriction.kind == "service_ban",
                UserRestriction.lifted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if active is not None:
        raise _error(status.HTTP_409_CONFLICT, "already_banned", "Пользователь уже заблокирован.")

    now = datetime.utcnow()
    row = UserRestriction(
        user_id=target.id,
        kind="service_ban",
        channel=None,
        reason=body.reason,
        source="manual",
        created_by_user_id=actor.user_id,
        created_at=now,
        checked_at=now,
        expires_at=_naive_utc(body.expires_at),
    )
    session.add(row)
    await session.flush()
    await _revoke_sessions(session, target.id)
    _audit(
        session,
        request,
        actor,
        target.id,
        "service_ban_created",
        new_value=str(row.id),
        reason=body.reason,
    )
    await session.commit()
    invalidate_actor_cache()
    return _restriction_view(row)


@router.delete(
    "/users/{user_id}/restrictions/{restriction_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def lift_service_ban(
    user_id: int,
    restriction_id: int,
    request: Request,
    session: SessionDep,
    actor: ManageServiceBanDep,
) -> None:
    row = await session.get(UserRestriction, restriction_id)
    if row is None or row.user_id != user_id or row.kind != "service_ban":
        raise _error(status.HTTP_404_NOT_FOUND, "not_found", "Ограничение не найдено.")
    if row.lifted_at is not None:
        return

    row.lifted_at = datetime.utcnow()
    _audit(
        session,
        request,
        actor,
        user_id,
        "service_ban_lifted",
        old_value=str(row.id),
        reason=row.reason,
    )
    await session.commit()
    invalidate_actor_cache()


@router.get("/audit", response_model=AuditPage)
async def list_audit(
    session: SessionDep,
    _actor: ManageServiceBanDep,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> AuditPage:
    total = (await session.execute(select(func.count(ModerationAudit.id)))).scalar_one()
    rows = (
        await session.execute(
            select(ModerationAudit)
            .order_by(ModerationAudit.created_at.desc(), ModerationAudit.id.desc())
            .offset(offset)
            .limit(limit)
        )
    ).scalars().all()
    return AuditPage(
        items=[
            AuditView(
                id=row.id,
                actor_user_id=row.actor_user_id,
                target_user_id=row.target_user_id,
                action=row.action,
                old_value=row.old_value,
                new_value=row.new_value,
                reason=row.reason,
                created_at=row.created_at,
            )
            for row in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )
