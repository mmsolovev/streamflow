"""Games endpoints."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import delete, select

from database.models import Game, GameMediaAsset, GameMetadataIGDB, streamer_games
from backend.deps import EditorDep, SessionDep, StreamerIdDep
from backend.repositories import games as repo
from backend.repositories.list_query import parse_list_query
from backend.schemas.common import Page
from backend.schemas.game import (
    CurrentStreamGame,
    GameDetail,
    GameIGDBRefreshIn,
    GameIGDBRefreshOut,
    GameReviewsUpdateIn,
    GameReviewsUpdateOut,
    GameStateUpdateIn,
    GameStateUpdateOut,
    GameStream,
    GameView,
)
from backend.schemas.media import (
    GameIGDBIdUpdateIn,
    GameIGDBIdUpdateOut,
    MediaUrlIn,
)
from services.media_asset_service import (
    MAX_IMAGE_BYTES,
    create_file_asset,
    get_or_create_url_asset,
    public_asset_url,
    set_game_media,
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
        review_links=item.get("review_links", []),
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


@router.get("/current-stream", response_model=list[CurrentStreamGame])
async def list_current_stream_games(
    session: SessionDep,
    streamer_id: StreamerIdDep,
) -> list[CurrentStreamGame]:
    """Игры текущего стрима и завершённых сессий, ожидающих агрегации статистики."""
    items = await repo.list_current_stream_games(session)
    game_views = await repo.get_game_list_views(
        session,
        streamer_id=streamer_id,
        game_ids=[
            int(item["game_id"])
            for item in items
            if item.get("game_id") is not None
        ],
    )
    for item in items:
        game_view = game_views.get(item.get("game_id"))
        item["game"] = _view(game_view) if game_view else None
    return [CurrentStreamGame(**item) for item in items]


@router.post("/{game_id}/refresh-igdb", response_model=GameIGDBRefreshOut)
async def refresh_game_igdb(
    game_id: int,
    body: GameIGDBRefreshIn,
    session: SessionDep,
    _user: EditorDep,
) -> GameIGDBRefreshOut:
    game = await session.get(Game, game_id)
    if game is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Игра не найдена.",
        )

    from services.game_metadata_service import (
        IGDBGameNotFound,
        IGDBMappingConflict,
        IGDBUpstreamError,
        InvalidIGDBReference,
        refresh_game_igdb as refresh_igdb,
    )

    try:
        metadata = await refresh_igdb(
            session,
            game_id=game_id,
            igdb_id=body.igdb_id,
            igdb_url=body.igdb_url,
        )
    except InvalidIGDBReference as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(error),
        ) from error
    except IGDBGameNotFound as error:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(error),
        ) from error
    except IGDBMappingConflict as error:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(error),
        ) from error
    except IGDBUpstreamError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(error),
        ) from error

    await session.commit()
    return GameIGDBRefreshOut(
        game_id=game_id,
        igdb_id=str(metadata.source_game_id),
        igdb_name=metadata.title,
        message=f"Данные IGDB для игры «{metadata.title}» обновлены.",
    )


@router.put("/{game_id}/cover/url")
async def set_game_cover_url(
    game_id: int,
    body: MediaUrlIn,
    session: SessionDep,
    actor: EditorDep,
) -> dict:
    game = await session.get(Game, game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="Игра не найдена.")
    try:
        asset = await get_or_create_url_asset(
            session,
            url=body.url,
            source="manual",
            created_by=actor.user_id,
        )
        await set_game_media(
            session,
            game_id=game_id,
            asset=asset,
            role="cover",
            source="manual",
        )
        await session.commit()
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"game_id": game_id, "cover_url": public_asset_url(asset)}


@router.post("/{game_id}/cover/file")
async def upload_game_cover(
    game_id: int,
    session: SessionDep,
    actor: EditorDep,
    file: UploadFile = File(...),
) -> dict:
    game = await session.get(Game, game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="Игра не найдена.")
    try:
        asset = await create_file_asset(
            session,
            data=await file.read(MAX_IMAGE_BYTES + 1),
            filename=file.filename,
            source="manual",
            created_by=actor.user_id,
        )
        await set_game_media(
            session,
            game_id=game_id,
            asset=asset,
            role="cover",
            source="manual",
        )
        await session.commit()
    except ValueError as error:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"game_id": game_id, "cover_url": public_asset_url(asset)}


@router.delete("/{game_id}/cover", status_code=status.HTTP_204_NO_CONTENT)
async def delete_game_cover(
    game_id: int,
    session: SessionDep,
    _actor: EditorDep,
) -> None:
    if await session.get(Game, game_id) is None:
        raise HTTPException(status_code=404, detail="Игра не найдена.")
    await session.execute(
        delete(GameMediaAsset).where(
            GameMediaAsset.game_id == game_id,
            GameMediaAsset.role == "cover",
            GameMediaAsset.source == "manual",
        )
    )
    await session.commit()


@router.patch("/{game_id}/igdb-id", response_model=GameIGDBIdUpdateOut)
async def update_game_igdb_id(
    game_id: int,
    body: GameIGDBIdUpdateIn,
    session: SessionDep,
    _actor: EditorDep,
) -> GameIGDBIdUpdateOut:
    game = await session.get(Game, game_id)
    if game is None:
        raise HTTPException(status_code=404, detail="Игра не найдена.")

    igdb_id = (body.igdb_id or "").strip()
    if not igdb_id:
        metadata = await session.get(GameMetadataIGDB, game_id)
        if metadata is not None:
            await session.delete(metadata)
        await session.execute(
            delete(GameMediaAsset).where(
                GameMediaAsset.game_id == game_id,
                GameMediaAsset.role == "cover",
                GameMediaAsset.source == "igdb",
            )
        )
        await session.commit()
        return GameIGDBIdUpdateOut(
            game_id=game_id,
            igdb_id=None,
            message="Связь игры с IGDB удалена. Игра сохранена.",
        )

    from services.game_metadata_service import (
        IGDBGameNotFound,
        IGDBMappingConflict,
        IGDBUpstreamError,
        InvalidIGDBReference,
        refresh_game_igdb as refresh_igdb,
    )

    try:
        metadata = await refresh_igdb(session, game_id=game_id, igdb_id=igdb_id)
    except InvalidIGDBReference as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except IGDBGameNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except IGDBMappingConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except IGDBUpstreamError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    await session.commit()
    return GameIGDBIdUpdateOut(
        game_id=game_id,
        igdb_id=str(metadata.source_game_id),
        message=f"IGDB ID игры обновлён на {metadata.source_game_id}.",
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
        review_links=item.get("review_links", []),
        genres=item["genres"],
        platforms=item["platforms"],
        igdb_id=item.get("igdb_id"),
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


@router.patch("/{game_id}/reviews", response_model=GameReviewsUpdateOut)
async def update_game_reviews(
    game_id: int,
    body: GameReviewsUpdateIn,
    session: SessionDep,
    _user: EditorDep,
) -> GameReviewsUpdateOut:
    game = await session.get(Game, game_id)
    if not game:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Игра не найдена.")

    game.review_links = [link.model_dump() for link in body.links]
    await session.commit()
    return GameReviewsUpdateOut(game_id=game_id, links=body.links)
