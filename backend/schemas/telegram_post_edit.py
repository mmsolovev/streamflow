"""DTOs for the Telegram post-stream editing admin section."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class PostEditSettingsView(BaseModel):
    enabled: bool
    delay_seconds: int
    header: str
    item: str
    separator: str
    footer: str
    link_label: str
    updated_at: Optional[datetime] = None


class PostEditSettingsPatch(BaseModel):
    enabled: Optional[bool] = None
    delay_seconds: Optional[int] = Field(None, ge=0, le=86400)
    header: Optional[str] = Field(None, max_length=1000)
    item: Optional[str] = Field(None, max_length=1000)
    separator: Optional[str] = Field(None, max_length=200)
    footer: Optional[str] = Field(None, max_length=1000)
    link_label: Optional[str] = Field(None, max_length=200)


class AnnouncementOption(BaseModel):
    id: int
    message_id: int
    posted_at: datetime
    media_kind: Optional[str]
    status: str
    manually_edited: bool
    preview: str
    link_urls: list[str]


class PostEditRunView(BaseModel):
    id: int
    stream_id: str
    stream_title: Optional[str]
    stream_started_at: Optional[datetime]
    stream_ended_at: Optional[datetime]
    announcement_id: Optional[int]
    status: str
    vod_url: Optional[str]
    last_error: Optional[str]
    selected_by_admin: bool
    check_at: Optional[datetime]
    applied_at: Optional[datetime]
    undone_at: Optional[datetime]


class PreviewView(BaseModel):
    text: str
    html: str
    media_kind: Optional[str]


class PostStreamView(BaseModel):
    settings: PostEditSettingsView
    target: Optional[PostEditRunView]
    runs: list[PostEditRunView]
    announcements: list[AnnouncementOption]
    preview: PreviewView


class RunActionIn(BaseModel):
    run_id: int


class SetTargetIn(BaseModel):
    run_id: int
    announcement_id: int


class VodCheckOut(BaseModel):
    available: bool
    vod_url: Optional[str] = None
    duration_minutes: Optional[int] = None
    error: Optional[str] = None
    checked_at: datetime


class ActionAcceptedOut(BaseModel):
    accepted: bool
    message: str
