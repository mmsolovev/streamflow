"""Reference data endpoints for frontend filters."""
from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import RECOMMENDATIONS_STREAMER_LOGIN
from database.models import Genre, Platform, StreamRuntimeSession, User, UserProfile
from backend.deps import SessionDep
from backend.schemas.user import ChannelInfo

router = APIRouter(prefix="/meta", tags=["meta"])


async def _is_channel_live(session: AsyncSession) -> bool:
    """Статус эфира: бот держит collecting-сессию, пока стрим идёт."""
    session_id = (
        await session.execute(
            select(StreamRuntimeSession.id)
            .where(
                StreamRuntimeSession.status == "collecting",
                StreamRuntimeSession.ended_at.is_(None),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return session_id is not None


@router.get("/channel", response_model=ChannelInfo)
async def get_channel(session: SessionDep) -> ChannelInfo:
    """Данные канала: логин, отображаемое имя, аватар и статус эфира."""
    login = RECOMMENDATIONS_STREAMER_LOGIN
    is_live = await _is_channel_live(session)
    profile = (
        await session.execute(
            select(UserProfile)
            .join(User, User.id == UserProfile.user_id)
            .where(UserProfile.login == login, UserProfile.is_current.is_(True))
        )
    ).scalar_one_or_none()
    if profile is None:
        return ChannelInfo(login=login, display_name=login, is_live=is_live)
    return ChannelInfo(
        login=profile.login or login,
        display_name=profile.display_name or profile.login or login,
        profile_image_url=profile.profile_image_url,
        twitch_url=profile.twitch_url,
        is_live=is_live,
    )


@router.get("/genres")
async def list_genres(session: SessionDep) -> dict:
    result = await session.execute(select(Genre).order_by(Genre.name.asc()))
    return {
        "items": [
            {"id": g.id, "name": g.name, "slug": g.slug, "abbreviation": g.abbreviation}
            for g in result.scalars().all()
        ]
    }


@router.get("/platforms")
async def list_platforms(session: SessionDep) -> dict:
    result = await session.execute(select(Platform).order_by(Platform.name.asc()))
    return {
        "items": [
            {"id": p.id, "name": p.name, "slug": p.slug, "abbreviation": p.abbreviation}
            for p in result.scalars().all()
        ]
    }