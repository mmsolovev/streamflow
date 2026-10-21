"""Streams endpoints."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, status

from backend.deps import SessionDep
from backend.repositories import streams as repo
from backend.repositories.list_query import parse_list_query
from backend.schemas.common import Page
from backend.schemas.stream import StreamView

router = APIRouter(prefix="/streams", tags=["streams"])


def _view(item: dict) -> StreamView:
    return StreamView(
        id=item["id"],
        started_at=item["started_at"],
        ended_at=item["ended_at"],
        duration_minutes=item["duration_minutes"],
        duration_hours=round((item["duration_minutes"] or 0) / 60, 1),
        title=item["title"],
        games=item["games"],
        tags=item["tags"],
        participants=item["participants"],
        vod_url=item["vod_url"],
        avg_viewers=item["avg_viewers"],
        max_viewers=item["max_viewers"],
    )


@router.get("/filters", response_model=dict)
async def streams_filter_options(session: SessionDep) -> dict:
    """Доступные значения тегов — для меню фильтров раздела «Стримы»."""
    return await repo.list_streams_filter_options(session)


@router.get("", response_model=Page[StreamView])
async def list_streams(
    session: SessionDep,
    search: str | None = Query(None, max_length=64),
    sort: str | None = Query(None, max_length=32),
    direction: str | None = Query(None, pattern="^(asc|desc)$"),
    filters: list[str] = Query(default=[]),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    date: datetime | None = Query(None, description="Фильтр по конкретному дню (ISO)"),
    from_: datetime | None = Query(None, alias="from", description="Начало окна (ISO)"),
    to: datetime | None = Query(None, description="Конец окна (ISO, включительно)"),
) -> Page[StreamView]:
    date_from = date or from_
    query = parse_list_query(
        search=search,
        sort=sort,
        direction=direction,
        filters=filters,
        default_direction="desc",
    )
    items, total, total_all, aggregates = await repo.list_streams(
        session,
        limit=limit,
        offset=offset,
        date_from=date_from,
        date_to=to,
        query=query,
    )
    return Page[StreamView](
        items=[_view(item) for item in items],
        total=total,
        total_all=total_all,
        aggregates=aggregates,
        limit=limit,
        offset=offset,
    )


@router.get("/{stream_id}", response_model=StreamView)
async def get_stream(stream_id: int, session: SessionDep) -> StreamView:
    item = await repo.get_stream(session, stream_id)
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Стрим не найден.")
    return _view(item)