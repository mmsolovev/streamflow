"""Games endpoints."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.dialects.postgresql import insert as pg_insert

from database.models import Game, streamer_games
from backend.deps import SessionDep, StreamerIdDep, StreamerOrAdminDep
from backend.repositories import games as repo
from backend.schemas.common import Page
from backend.schemas.game import GameDetail, GameStateUpdateIn, GameStateUpdateOut, GameView

router = APIRouter(prefix="/games", tags=["games"])


def _view(item: dict) -> GameView:
    return GameView(
        id=item["id"],
        name=item["name"],
        rank=item["rank"],
        streams_count=item["streams_count"],
        hours=round((item["duration_minutes"] or 0) / 60, 1),
        last_stream=item["last_stream"],
        hltb_all_styles=item["hltb_all_styles"],
        steam_url=item["steam_url"],
        liked=item["liked"],
        completed=item["completed"],
        tags=item["tags"],
    )


@router.get("", response_model=Page[GameView])
async def list_games(
    session: SessionDep,
    streamer_id: StreamerIdDep,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Page[GameView]:
    items, total = await repo.list_games(
        session, streamer_id=streamer_id, limit=limit, offset=offset
    )
    return Page[GameView](
        items=[_view(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/search", response_model=dict)
async def search_games(
    q: str = Query(..., min_length=1, max_length=200),
) -> dict:
    from services.games_service import find_game_lookup

    match = await find_game_lookup(q)
    if not match:
        return {"query": q, "match": None}
    return {
        "query": q,
        "match": {
            "name": match.name,
            "streams_count": match.streams_count,
            "last_stream": match.last_stream,
            "hours": match.hours_streamed,
            "rank": match.rank,
            "liked": match.liked,
            "completed": match.completed,
        },
    }


@router.get("/{game_id}", response_model=GameDetail)
async def get_game(
    game_id: int,
    session: SessionDep,
    streamer_id: StreamerIdDep,
) -> GameDetail:
    item = await repo.get_game(session, game_id, streamer_id=streamer_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Игра не найдена.")
    return GameDetail(
        id=item["id"],
        name=item["name"],
        rank=item.get("rank", 0),
        streams_count=item["streams_count"],
        hours=round((item["duration_minutes"] or 0) / 60, 1),
        last_stream=item["last_stream"],
        hltb_all_styles=item["hltb_all_styles"],
        steam_url=item["steam_url"],
        liked=item["liked"],
        completed=item["completed"],
        tags=item["tags"],
        genres=item["genres"],
        platforms=item["platforms"],
        slug=item["slug"],
        game_type=item["game_type"],
    )


@router.patch("/{game_id}/streamer-state", response_model=GameStateUpdateOut)
async def update_streamer_state(
    game_id: int,
    body: GameStateUpdateIn,
    session: SessionDep,
    streamer_id: StreamerIdDep,
    _user: StreamerOrAdminDep,
) -> GameStateUpdateOut:
    game = await session.get(Game, game_id)
    if not game:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Игра не найдена.")

    stmt = pg_insert(streamer_games).values(
        streamer_id=streamer_id,
        game_id=game_id,
        liked=body.liked,
        completed=body.completed,
        updated_at=datetime.utcnow(),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[streamer_games.c.streamer_id, streamer_games.c.game_id],
        set_={
            "liked": stmt.excluded.liked,
            "completed": stmt.excluded.completed,
            "updated_at": stmt.excluded.updated_at,
        },
    )
    await session.execute(stmt)
    await session.commit()
    return GameStateUpdateOut(game_id=game_id, liked=body.liked, completed=body.completed)