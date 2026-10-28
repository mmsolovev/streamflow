"""Recommendations endpoints (СОВЕТЫ list + write path reusing domain service)."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, status

from pipeline.ingest.igdb_api import search_recommendation_candidates
from pipeline.load.load_recommendations import (
    find_user_recommendation,
    remove_recommendation,
)
from backend.deps import CurrentActorDep, CurrentUserDep, SessionDep, current_user_login
from backend.repositories import recommendations as repo
from backend.repositories.list_query import parse_list_query
from backend.schemas.common import Page
from backend.schemas.recommendation import (
    GameCandidate,
    RecommendationActionOut,
    RecommendationAddBody,
    RecommendationDeleteOut,
    RecommendationSearchOut,
    RecommendationView,
)
from services.authz_service import Capability

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


def _view(item: dict) -> RecommendationView:
    return RecommendationView(**item)


def _target_list(release_date: datetime | None) -> str:
    """Куда попадает игра: ещё не вышла (или нет даты) → Релизы, иначе → Советы."""
    if release_date is None:
        return "releases"
    release = release_date if release_date.tzinfo else release_date.replace(tzinfo=timezone.utc)
    return "releases" if release > datetime.now(timezone.utc) else "recommendations"


@router.get("/filters", response_model=dict)
async def recommendations_filter_options(session: SessionDep) -> dict:
    """Доступные значения фильтров раздела «Советы»."""
    return await repo.list_recommendations_filter_options(session)


@router.get("", response_model=Page[RecommendationView])
async def list_recommendations(
    session: SessionDep,
    search: str | None = Query(None, max_length=64),
    sort: str | None = Query(None, max_length=32),
    direction: str | None = Query(None, pattern="^(asc|desc)$"),
    filters: list[str] = Query(default=[]),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Page[RecommendationView]:
    # Чистим устаревшие Twitch-рекомендации перед формированием списка.
    from services.recommendations_service import refresh_recommendation_lifecycle

    await refresh_recommendation_lifecycle()

    query = parse_list_query(
        search=search,
        sort=sort,
        direction=direction,
        filters=filters,
        default_direction="desc",
    )
    items, total, total_all, aggregates = await repo.list_recommendations(
        session, limit=limit, offset=offset, query=query
    )
    return Page[RecommendationView](
        items=[_view(item) for item in items],
        total=total,
        total_all=total_all,
        aggregates=aggregates,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=RecommendationActionOut)
async def add_recommendation(
    body: RecommendationAddBody,
    user: CurrentUserDep,
    actor: CurrentActorDep,
) -> RecommendationActionOut:
    from services.recommendations_service import recommend_game

    if not actor.can(Capability.RECOMMEND):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Добавление рекомендаций ограничено для этого аккаунта.",
        )
    login, display_name = current_user_login(user)
    target_login = (body.user_login or login).strip().casefold()
    if target_login != login.casefold() and not actor.can(Capability.EDIT_TABLES):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Добавлять рекомендации от чужого имени может только администратор.",
        )
    result = await recommend_game(
        body.query,
        target_login,
        display_name if target_login == login.casefold() else target_login,
        igdb_id=body.igdb_id,
        note=body.note,
    )

    recommendation = None
    target_list = None
    if result.recommendation is not None:
        summary = result.recommendation
        recommendation = RecommendationView(
            id=summary.id,
            title=summary.title,
            status=summary.status,
            release_date=summary.release_date,
            release_delta_days=None,
            steam_url=summary.steam_url,
            igdb_score=summary.igdb_score,
            cover_url=summary.cover_url,
            description_ru=None,
            description_en=None,
            votes_count=summary.votes_count,
            recommenders=", ".join(summary.recommenders),
            tags="",
        )
        target_list = _target_list(summary.release_date)

    if result.outcome == "forbidden":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=result.message)
    if result.outcome == "already_streamed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=result.message)
    if result.outcome == "not_found":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result.message)
    if result.outcome == "invalid":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=result.message)

    return RecommendationActionOut(
        outcome=result.outcome,
        message=result.message,
        recommendation=recommendation,
        target_list=target_list,
    )


@router.delete("/{game_id}", response_model=RecommendationDeleteOut)
async def delete_recommendation(
    game_id: int,
    session: SessionDep,
    user: CurrentUserDep,
    actor: CurrentActorDep,
    user_login: str | None = Query(
        None,
        description="Логин рекомендовавшего (для админов; без параметра — своя рекомендация).",
    ),
) -> RecommendationDeleteOut:
    if not actor.can(Capability.RECOMMEND):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Удаление рекомендаций ограничено для этого аккаунта.",
        )
    login, _ = current_user_login(user)
    target_login = (user_login or login).strip().lower()
    if target_login != login and not actor.can(Capability.EDIT_TABLES):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Удалять чужие рекомендации может только администратор.",
        )
    user_rec = await find_user_recommendation(session, game_id, target_login)
    if not user_rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Рекомендация не найдена.",
        )
    await remove_recommendation(session, user_rec["user_id"], user_rec["game_id"])
    await session.commit()
    return RecommendationDeleteOut(outcome="deleted", message="Рекомендация удалена.")


@router.get("/search", response_model=RecommendationSearchOut)
async def search_recommendations(
    query: str = Query(..., min_length=1, max_length=120),
) -> RecommendationSearchOut:
    """Поиск вариантов игр из IGDB для окна «Предложить игру»."""
    candidates_meta = await search_recommendation_candidates(query)
    candidates = []
    for meta in candidates_meta:
        release_year = None
        if meta.release_date:
            try:
                release_year = meta.release_date.year
            except Exception:
                release_year = None
        candidates.append(
            GameCandidate(
                igdb_id=meta.source_game_id,
                title=meta.title,
                release_year=release_year,
                platforms=meta.platforms_text,
                genres=meta.genres_text,
            )
        )
    return RecommendationSearchOut(query=query, candidates=candidates)