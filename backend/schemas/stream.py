"""Stream DTOs (mirror of the СТРИМЫ worksheet)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class StreamView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    started_at: datetime
    ended_at: Optional[datetime]
    duration_minutes: Optional[int]
    duration_hours: float
    title: str
    games: list[str]
    tags: list[str]
    participants: list[str]
    vod_url: Optional[str]
    avg_viewers: Optional[int]
    max_viewers: Optional[int]