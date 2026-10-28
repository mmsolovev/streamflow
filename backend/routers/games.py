"""Games endpoints."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy.dialects.postgresql import insert as pg_insert

from database.models import Game, streamer_games
from backend.deps import EditorDep, SessionDep, StreamerIdDep
from backend.repositories import games as repo
from backend.repositories.list_query import parse_list_query
from backend.schemas.common import Page
from backend.schemas.game import (
    GameDetail,
    GameStateUpdateIn,
    GameStateUpdateOut,
    GameStream,
    GameView,
)

router = APIRouter(prefix="/games", tags=["games"])


def _view(item: dict) -> GameView:
    return GameView(
        id=item["id"],
        name=item["name"],
        rank=item["rank"],
        streams_count=item["streams_count"],
        hours=round((item["duration_minutes"] or 0) / 60, 1),
        duration_minutes=item["duration_minutes"],
        last_stream=item["last_stream"],
        last_stream_id=item.get("last_stream_id"),
        hltb_all_styles=item["hltb_all_styles"],
        steam_url=item["steam_url"],
        cover_url=item["cover_url"],
        liked=item["liked"],
        completed=item["completed"],
        tags=item["tags"],
    )


@router.get("", response_model=Page[GameView])
async def list_games(
    session: SessionDep,
    streamer_id: StreamerIdDep,
    search: str | None = Query(None, max_length=64),
    sort: str | None = Query(None, max_length=32),
    direction: str | None = Query(None, pattern="^(asc|desc)$"),
    filters: list[str] = Query(default=[]),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Page[GameView]:
    query = parse_list_query(
        search=search,
        sort=sort,
        direction=direction,
        filters=filters,
        default_direction="desc",
    )
    items, total, total_all, aggregates = await repo.list_games(
        session, streamer_id=streamer_id, limit=limit, offset=offset, query=query
    )
    return Page[GameView](
        items=[_view(item) for item in items],
        total=total,
        total_all=total_all,
        aggregates=aggregates,
        limit=limit,
        offset=offset,
    )


@router.get("/covers", response_model=list[dict])
async def games_covers(session: SessionDep) -> list[dict]:
    """Имя → обложка игры (для полосы обложек в разделе «Стримы»)."""
    return await repo.list_games_covers(session)


@router.get("/filters", response_model=dict)
async def games_filter_options(session: SessionDep) -> dict:
    """Доступные значения тегов — для меню фильтров раздела «Игры»."""
    return await repo.list_games_filter_options(session)


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
        duration_minutes=item["duration_minutes"],
        last_stream=item["last_stream"],
        last_stream_id=item.get("last_stream_id"),
        hltb_all_styles=item["hltb_all_styles"],
        steam_url=item["steam_url"],
        cover_url=item["cover_url"],
        liked=item["liked"],
        completed=item["completed"],
        tags=item["tags"],
        genres=item["genres"],
        platforms=item["platforms"],
        slug=item["slug"],
        game_type=item["game_type"],
        release_date=item.get("release_date"),
        release_delta_days=item.get("release_delta_days"),
        description_ru=item.get("description_ru"),
        description_en=item.get("description_en"),
        recommenders_list=item.get("recommenders_list", []),
        recommenders_count=item.get("recommenders_count", 0),
        interested=item.get("interested", False),
        hltb_id=item.get("hltb_id"),
        hltb_main_story=item.get("hltb_main_story"),
        hltb_main_extra=item.get("hltb_main_extra"),
        hltb_completionist=item.get("hltb_completionist"),
        hltb_coop=item.get("hltb_coop"),
        hltb_multiplayer=item.get("hltb_multiplayer"),
        streams=item.get("streams", []),
        streams_total=item.get("streams_total", 0),
        in_games=item.get("in_games", True),
        in_releases=item.get("in_releases", False),
        in_recommendations=item.get("in_recommendations", False),
    )


@router.get("/{game_id}/streams", response_model=Page[GameStream])
async def list_game_streams(
    game_id: int,
    session: SessionDep,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> Page[GameStream]:
    """Стримы по игре — догрузка длинного списка на странице игры."""
    items, total = await repo.list_game_streams(
        session, game_id, limit=limit, offset=offset
    )
    return Page[GameStream](
        items=[GameStream(**item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.patch("/{game_id}/streamer-state", response_model=GameStateUpdateOut)
async def update_streamer_state(
    game_id: int,
    body: GameStateUpdateIn,
    session: SessionDep,
    streamer_id: StreamerIdDep,
    _user: EditorDep,
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