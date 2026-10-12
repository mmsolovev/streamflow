"""Recommendation DTOs (mirror of СОВЕТЫ worksheet + domain service)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class RecommendationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    status: str
    release_date: Optional[datetime]
    steam_url: Optional[str]
    igdb_score: Optional[float]
    cover_url: Optional[str]
    votes_count: int
    recommenders: str
    release_delta_days: Optional[int]


class RecommendationAddBody(BaseModel):
    query: str


class RecommendationActionOut(BaseModel):
    outcome: str
    message: str
    recommendation: Optional[RecommendationView] = None


class RecommendationDeleteOut(BaseModel):
    outcome: str
    message: str