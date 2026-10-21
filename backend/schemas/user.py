"""User DTOs."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class UserSuggestion(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    login: str | None = None
    display_name: str | None = None


class ChannelInfo(BaseModel):
    """Данные канала — для сайдбара (логин, имя, аватар)."""

    login: str
    display_name: str
    profile_image_url: str | None = None
    twitch_url: str | None = None
