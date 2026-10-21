"""Auth/user DTOs."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class UserView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    login: Optional[str] = None
    display_name: Optional[str] = None
    is_streamer: bool = False
    is_admin: bool = False


class StreamerAuthorizationView(BaseModel):
    """Статус «стримерского» токена для одного логина."""

    login: str
    connected: bool = False
    scopes: Optional[str] = None
    expires_at: Optional[datetime] = None


class StreamerAuthStatus(BaseModel):
    """Ответ `/auth/streamer/status`: что запрашиваем и что уже подключено."""

    requested_scopes: list[str] = []
    streamers: list[StreamerAuthorizationView] = []
