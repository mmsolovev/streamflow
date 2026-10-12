"""Recommendations endpoints (СОВЕТЫ list + write path reusing domain service)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from pipeline.load.load_recommendations import (
    find_user_recommendation,
    remove_recommendation,
)
from backend.deps import CurrentUserDep, SessionDep, current_user_login
from backend.repositories import recommendations as repo
from backend.schemas.common import Page
from backend.schemas.recommendation import (
    RecommendationActionOut,
    RecommendationAddBody,
    RecommendationDeleteOut,
    RecommendationView,
)

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


def _view(item: dict) -> RecommendationView:
    return RecommendationView(**item)


@router.get("", response_model=Page[RecommendationView])
async def list_recommendations(
    session: SessionDep,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Page[RecommendationView]:
    items, total = await repo.list_recommendations(session, limit=limit, offset=offset)
    return Page[RecommendationView](
        items=[_view(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=RecommendationActionOut)
async def add_recommendation(
    body: RecommendationAddBody,
    user: CurrentUserDep,
) -> RecommendationActionOut:
    from services.recommendations_service import recommend_game

    login, display_name = current_user_login(user)
    result = await recommend_game(body.query, login, display_name)

    recommendation = None
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
            votes_count=summary.votes_count,
            recommenders=", ".join(summary.recommenders),
        )

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
    )


@router.delete("/{game_id}", response_model=RecommendationDeleteOut)
async def delete_recommendation(
    game_id: int,
    session: SessionDep,
    user: CurrentUserDep,
) -> RecommendationDeleteOut:
    login, _ = current_user_login(user)
    user_rec = await find_user_recommendation(session, game_id, login)
    if not user_rec:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Рекомендация не найдена.",
        )
    await remove_recommendation(session, user_rec["user_id"], user_rec["game_id"])
    await session.commit()
    return RecommendationDeleteOut(outcome="deleted", message="Рекомендация удалена.")