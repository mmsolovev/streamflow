"""Releases endpoints (upcoming + unknown date recommendations)."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.dialects.postgresql import insert as pg_insert

from database.models import Game, streamer_games
from backend.deps import SessionDep, StreamerIdDep, StreamerOrAdminDep
from backend.repositories import releases as repo
from backend.schemas.common import Page
from backend.schemas.release import InterestUpdateIn, InterestUpdateOut, ReleaseView

router = APIRouter(prefix="/releases", tags=["releases"])


def _view(item: dict) -> ReleaseView:
    return ReleaseView(**item)


@router.get("", response_model=Page[ReleaseView])
async def list_releases(
    session: SessionDep,
    streamer_id: StreamerIdDep,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Page[ReleaseView]:
    items, total = await repo.list_releases(
        session, streamer_id=streamer_id, limit=limit, offset=offset
    )
    return Page[ReleaseView](
        items=[_view(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.patch("/{game_id}/interested", response_model=InterestUpdateOut)
async def set_interested(
    game_id: int,
    body: InterestUpdateIn,
    session: SessionDep,
    streamer_id: StreamerIdDep,
    _user: StreamerOrAdminDep,
) -> InterestUpdateOut:
    game = await session.get(Game, game_id)
    if not game:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Игра не найдена.")

    stmt = pg_insert(streamer_games).values(
        streamer_id=streamer_id,
        game_id=game_id,
        interested=body.interested,
        updated_at=datetime.utcnow(),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[streamer_games.c.streamer_id, streamer_games.c.game_id],
        set_={
            "interested": stmt.excluded.interested,
            "updated_at": stmt.excluded.updated_at,
        },
    )
    await session.execute(stmt)
    await session.commit()
    return InterestUpdateOut(game_id=game_id, interested=body.interested)