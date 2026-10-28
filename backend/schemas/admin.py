"""DTOs for role and restriction administration."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class RestrictionView(BaseModel):
    id: int
    kind: str
    channel: Optional[str] = None
    reason: Optional[str] = None
    source: str
    expires_at: Optional[datetime] = None
    created_at: datetime
    created_by_user_id: Optional[int] = None


class AdminUserView(BaseModel):
    id: int
    login: Optional[str] = None
    display_name: Optional[str] = None
    role: str
    display_role: str
    is_twitch_banned: bool = False
    is_service_banned: bool = False
    restrictions: list[RestrictionView] = []
    created_at: Optional[datetime] = None


class AdminUserPage(BaseModel):
    items: list[AdminUserView]
    total: int
    limit: int
    offset: int


class RoleChangeBody(BaseModel):
    role: str = Field(..., pattern="^(streamer|admin|editor|user)$")
    reason: Optional[str] = Field(None, max_length=500)


class ServiceBanBody(BaseModel):
    reason: Optional[str] = Field(None, max_length=500)
    expires_at: Optional[datetime] = None


class AuditView(BaseModel):
    id: int
    actor_user_id: Optional[int] = None
    target_user_id: Optional[int] = None
    action: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None
    reason: Optional[str] = None
    created_at: datetime


class AuditPage(BaseModel):
    items: list[AuditView]
    total: int
    limit: int
    offset: int
