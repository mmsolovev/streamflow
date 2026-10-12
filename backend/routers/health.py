"""Health/liveness endpoints."""
from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from backend.deps import SessionDep

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(session: SessionDep) -> dict:
    db_ok = True
    try:
        await session.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    return {"status": "ok" if db_ok else "degraded", "database": "ok" if db_ok else "error"}