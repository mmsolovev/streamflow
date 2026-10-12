"""Reference data endpoints for frontend filters."""
from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from database.models import Genre, Platform
from backend.deps import SessionDep

router = APIRouter(prefix="/meta", tags=["meta"])


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