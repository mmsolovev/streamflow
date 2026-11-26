"""Read-only media catalog DTOs."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class MediaGameRef(BaseModel):
    id: int
    name: str


class RecordingView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    twitch_video_id: str | None
    title: str
    url: str
    thumbnail_url: str | None
    recorded_at: datetime | None
    duration_minutes: int | None
    views_count: int | None
    stream_id: int
    stream_title: str | None
    games: list[str]
    game_refs: list[MediaGameRef]


class ClipView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    external_id: str
    title: str
    url: str
    thumbnail_url: str | None
    created_at: datetime
    duration_seconds: int | None
    views_count: int | None
    stream_id: int
    stream_title: str | None
    game_id: int | None
    game_name: str | None
    creator_user_id: int | None
    creator_login: str | None
    creator_display_name: str | None


class MediaFilterOption(BaseModel):
    key: str
    label: str


class MediaFilterOptions(BaseModel):
    games: list[MediaFilterOption]
    creators: list[MediaFilterOption]
    streams: list[MediaFilterOption]


class MediaAssetOut(BaseModel):
    id: int
    url: str
    storage_kind: str


class MediaUrlIn(BaseModel):
    url: str


class RecordingPreviewOut(BaseModel):
    recording_id: int
    thumbnail_url: str | None
    message: str


class SocialLinkView(BaseModel):
    id: int
    service_key: str
    name: str
    url: str
    description: str
    icon_url: str | None
    sort_order: int
    is_active: bool


class SocialLinkCreateIn(BaseModel):
    service_key: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,39}$")
    name: str
    url: str = "#"
    description: str = ""
    sort_order: int = 0
    is_active: bool = True


class SocialLinkUpdateIn(BaseModel):
    name: str | None = None
    url: str | None = None
    description: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class GameIGDBIdUpdateIn(BaseModel):
    igdb_id: str | None


class GameIGDBIdUpdateOut(BaseModel):
    game_id: int
    igdb_id: str | None
    message: str
