"""Stream DTOs (mirror of the СТРИМЫ worksheet)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class StreamParticipant(BaseModel):
    """Участник стрима со ссылкой на профиль Twitch."""

    user_id: int
    login: str | None = None
    display_name: str | None = None
    twitch_url: str | None = None


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
    participants: list[StreamParticipant]
    vod_url: Optional[str]
    avg_viewers: Optional[int]
    max_viewers: Optional[int]


class StreamParticipantAddIn(BaseModel):
    """Добавление участника на стрим по логину Twitch."""

    user_login: str


class StreamParticipantActionOut(BaseModel):
    outcome: str
    message: str
    participant: StreamParticipant | None = None


class StreamParticipantDeleteOut(BaseModel):
    outcome: str
    message: str