"""Users endpoints (search for autocomplete)."""
from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import and_, func, or_, select

from backend.deps import SessionDep
from backend.schemas.common import Page
from backend.schemas.user import UserSuggestion
from database.models import User, UserProfile

router = APIRouter(prefix="/users", tags=["users"])


def _match(term: str):
    """Совпадение по логину или по отображаемому имени."""
    like = f"%{term}%"
    return and_(
        UserProfile.is_current.is_(True),
        or_(
            func.lower(UserProfile.login).like(like),
            func.lower(UserProfile.display_name).like(like),
        ),
    )


@router.get("/search", response_model=Page[UserSuggestion])
async def search_users(
    session: SessionDep,
    q: str = Query(..., min_length=1, max_length=64),
    limit: int = Query(10, ge=1, le=20),
    offset: int = Query(0, ge=0),
) -> Page[UserSuggestion]:
    term = q.strip().casefold()
    subq = (
        select(User.id)
        .join(UserProfile, UserProfile.user_id == User.id)
        .where(_match(term))
        .distinct()
    )
    count = (
        await session.execute(select(func.count()).select_from(subq))
    ).scalar_one_or_none() or 0

    rows_q = (
        select(UserProfile.login, UserProfile.display_name)
        .join(User, User.id == UserProfile.user_id)
        .where(_match(term))
        .order_by(func.lower(UserProfile.login).asc())
        .offset(offset)
        .limit(limit)
    )
    rows = (await session.execute(rows_q)).all()

    items = [
        UserSuggestion(
            login=row[0],
            display_name=row[1] or row[0],
        )
        for row in rows
    ]
    return Page[UserSuggestion](items=items, total=count, limit=limit, offset=offset)
