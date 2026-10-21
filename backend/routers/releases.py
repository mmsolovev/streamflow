"""Releases endpoints (upcoming + unknown date recommendations)."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.dialects.postgresql import insert as pg_insert

from database.models import Game, streamer_games
from backend.deps import AdminDep, SessionDep, StreamerIdDep
from backend.repositories import releases as repo
from backend.repositories.list_query import parse_list_query
from backend.schemas.common import Page
from backend.schemas.release import InterestUpdateIn, InterestUpdateOut, ReleaseView
from config.settings import RECOMMENDATIONS_STREAMER_DISPLAY_NAME, RECOMMENDATIONS_STREAMER_LOGIN
from pipeline.load.load_recommendations import set_release_interest_recommendation

router = APIRouter(prefix="/releases", tags=["releases"])

# Отметка «Интересно» дублируется рекомендацией канала: «Ожидаемая новинка
# по версии Tabula».
RELEASE_INTEREST_NOTE = f"Ожидаемая новинка по версии {RECOMMENDATIONS_STREAMER_DISPLAY_NAME}"


def _view(item: dict) -> ReleaseView:
    return ReleaseView(**item)


@router.get("/filters", response_model=dict)
async def releases_filter_options(session: SessionDep) -> dict:
    """Доступные значения фильтров раздела «Релизы»."""
    return await repo.list_releases_filter_options(session)


@router.get("", response_model=Page[ReleaseView])
async def list_releases(
    session: SessionDep,
    streamer_id: StreamerIdDep,
    search: str | None = Query(None, max_length=64),
    sort: str | None = Query(None, max_length=32),
    direction: str | None = Query(None, pattern="^(asc|desc)$"),
    filters: list[str] = Query(default=[]),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Page[ReleaseView]:
    query = parse_list_query(
        search=search,
        sort=sort,
        direction=direction,
        filters=filters,
        default_direction="asc",
    )
    items, total, total_all, aggregates = await repo.list_releases(
        session,
        streamer_id=streamer_id,
        limit=limit,
        offset=offset,
        query=query,
    )
    return Page[ReleaseView](
        items=[_view(item) for item in items],
        total=total,
        total_all=total_all,
        aggregates=aggregates,
        limit=limit,
        offset=offset,
    )


@router.patch("/{game_id}/interested", response_model=InterestUpdateOut)
async def set_interested(
    game_id: int,
    body: InterestUpdateIn,
    session: SessionDep,
    streamer_id: StreamerIdDep,
    _user: AdminDep,
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
    # Отметка «Интересно» = рекомендация канала: «Ожидаемая новинка по версии Tabula».
    await set_release_interest_recommendation(
        session,
        game_id,
        user_login=RECOMMENDATIONS_STREAMER_LOGIN,
        note=RELEASE_INTEREST_NOTE,
        interested=body.interested,
    )
    await session.commit()
    return InterestUpdateOut(game_id=game_id, interested=body.interested)