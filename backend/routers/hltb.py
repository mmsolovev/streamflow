"""HowLongToBeat endpoints (данные из `game_metadata_hltb`)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from backend.deps import AdminDep, SessionDep
from backend.repositories import hltb as repo
from backend.repositories.list_query import parse_list_query
from backend.schemas.common import Page
from backend.schemas.hltb import (
    HltbAddIn,
    HltbAddOut,
    HltbLookupIn,
    HltbLookupOut,
    HltbView,
)
from services.hltb_service import add_hltb_game_by_url, lookup_hltb_by_url

router = APIRouter(prefix="/hltb", tags=["hltb"])


@router.get("", response_model=Page[HltbView])
async def list_hltb(
    session: SessionDep,
    search: str | None = Query(None, max_length=64),
    sort: str | None = Query(None, max_length=32),
    direction: str | None = Query(None, pattern="^(asc|desc)$"),
    filters: list[str] = Query(default=[]),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Page[HltbView]:
    query = parse_list_query(
        search=search, sort=sort, direction=direction, filters=filters
    )
    items, total, total_all, aggregates = await repo.list_hltb(
        session, limit=limit, offset=offset, query=query
    )
    return Page[HltbView](
        items=[HltbView(**item) for item in items],
        total=total,
        total_all=total_all,
        aggregates=aggregates,
        limit=limit,
        offset=offset,
    )


@router.post("/lookup", response_model=HltbLookupOut)
async def lookup_hltb(body: HltbLookupIn, _user: AdminDep) -> HltbLookupOut:
    """Ищет игру по ссылке HowLongToBeat — для предпросмотра перед добавлением."""
    result = await lookup_hltb_by_url(body.url)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Не удалось найти игру по ссылке. Проверьте адрес и попробуйте снова.",
        )
    return HltbLookupOut(**result)


@router.post("", response_model=HltbAddOut)
async def add_hltb(body: HltbAddIn, _user: AdminDep) -> HltbAddOut:
    """Добавляет игру по ссылке HowLongToBeat: сохраняет HLTB и обновляет IGDB."""
    result = await add_hltb_game_by_url(body.url, body.game_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Не удалось добавить игру. Проверьте ссылку и попробуйте снова.",
        )
    return HltbAddOut(
        game_id=result["game_id"],
        game_name=result["game_name"],
        hltb_id=result["hltb_id"],
        hltb_name=result["hltb_name"],
        all_styles=result["all_styles"],
        message=f"«{result['game_name']}» добавлена в раздел HowLongToBeat.",
    )
