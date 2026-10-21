"""Release DTOs (mirror of the РЕЛИЗЫ worksheet)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class Recommender(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_login: Optional[str] = None
    display_name: Optional[str] = None
    recommendation_note: Optional[str] = None


class ReleaseView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    release_date: Optional[datetime]
    release_delta_days: Optional[int]
    steam_url: Optional[str]
    description_ru: Optional[str]
    description_en: Optional[str]
    cover_url: Optional[str]
    interested: bool
    tags: str
    recommenders: str
    recommenders_tooltip: Optional[str] = None
    recommenders_list: list[Recommender] = []
    recommenders_count: int


class InterestUpdateIn(BaseModel):
    interested: bool


class InterestUpdateOut(BaseModel):
    game_id: int
    interested: bool