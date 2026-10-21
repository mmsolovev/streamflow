"""Recommendation DTOs (mirror of СОВЕТЫ worksheet + domain service)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class RecommenderEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_login: Optional[str] = None
    display_name: Optional[str] = None
    recommendation_note: Optional[str] = None


class RecommendationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    status: str
    release_date: Optional[datetime]
    steam_url: Optional[str]
    igdb_score: Optional[float]
    cover_url: Optional[str]
    description_ru: Optional[str]
    description_en: Optional[str]
    votes_count: int
    recommenders: str
    recommenders_tooltip: Optional[str] = None
    recommenders_list: list[RecommenderEntry] = []
    tags: str
    release_delta_days: Optional[int]


class RecommendationAddBody(BaseModel):
    query: str
    # Выбор кандидата IGDB id (применяется при выборе из подсказок поиска).
    igdb_id: Optional[str] = None
    # Комментарий пользователя для recommendation_note
    note: Optional[str] = None
    # Логин пользователя, от имени которого добавить рекомендацию (только для админов).
    user_login: Optional[str] = None


class RecommendationActionOut(BaseModel):
    outcome: str
    message: str
    recommendation: Optional[RecommendationView] = None
    # Куда попала игра: "releases" (ещё не вышла) или "recommendations" (вышла).
    target_list: Optional[str] = None


class RecommendationDeleteOut(BaseModel):
    outcome: str
    message: str


class GameCandidate(BaseModel):
    """Вариант игры из IGDB для окна «Предложить игру»."""

    igdb_id: str
    title: str
    release_year: Optional[int] = None
    platforms: Optional[str] = None
    genres: Optional[str] = None


class RecommendationSearchOut(BaseModel):
    query: str
    candidates: list[GameCandidate] = []