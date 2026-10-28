"""Game DTOs (mirror of the ИГРЫ worksheet)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from backend.schemas.recommendation import RecommenderEntry


class GameView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    rank: int
    streams_count: int
    hours: float
    duration_minutes: Optional[int]
    last_stream: Optional[datetime]
    last_stream_id: Optional[int] = None
    hltb_all_styles: Optional[float]
    steam_url: Optional[str]
    cover_url: Optional[str]
    liked: bool
    completed: bool
    tags: str


class GameDetail(GameView):
    genres: list[str]
    platforms: list[str]
    slug: Optional[str]
    game_type: Optional[str]
    # Данные из «РЕЛИЗОВ» и «СОВЕТОВ» — для страницы игры.
    release_date: Optional[datetime] = None
    release_delta_days: Optional[int] = None
    description_ru: Optional[str] = None
    description_en: Optional[str] = None
    recommenders_list: list[RecommenderEntry] = []
    recommenders_count: int = 0
    # Отметка «Интересно» (из «РЕЛИЗОВ»).
    interested: bool = False
    # Все времена HowLongToBeat.
    hltb_id: Optional[str] = None
    hltb_main_story: Optional[float] = None
    hltb_main_extra: Optional[float] = None
    hltb_completionist: Optional[float] = None
    hltb_coop: Optional[float] = None
    hltb_multiplayer: Optional[float] = None
    # Стримы, на которых играли в эту игру (от новейших к старым).
    streams: list[GameStream] = []
    # Всего стримов по игре (в `streams` — только первые `GAME_STREAMS_PREVIEW`).
    streams_total: int = 0
    # В каких листах «Статистики» присутствует игра.
    in_games: bool = True
    in_releases: bool = False
    in_recommendations: bool = False


class GameStream(BaseModel):
    """Стрим, на котором играли в игру (для страницы игры)."""

    id: int
    started_at: Optional[datetime] = None
    duration_minutes: Optional[int] = None
    title: str = ""
    vod_url: Optional[str] = None


class GameStateUpdateIn(BaseModel):
    liked: bool
    completed: bool


class GameStateUpdateOut(BaseModel):
    game_id: int
    liked: bool
    completed: bool