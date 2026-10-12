"""Game DTOs (mirror of the ИГРЫ worksheet)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class GameView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    rank: int
    streams_count: int
    hours: float
    last_stream: Optional[datetime]
    hltb_all_styles: Optional[float]
    steam_url: Optional[str]
    liked: bool
    completed: bool
    tags: str


class GameDetail(GameView):
    genres: list[str]
    platforms: list[str]
    slug: Optional[str]
    game_type: Optional[str]


class GameStateUpdateIn(BaseModel):
    liked: bool
    completed: bool


class GameStateUpdateOut(BaseModel):
    game_id: int
    liked: bool
    completed: bool