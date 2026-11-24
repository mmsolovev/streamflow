"""Game DTOs (mirror of the ИГРЫ worksheet)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.schemas.recommendation import RecommenderEntry


class GameReviewLink(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    url: str = Field(min_length=1, max_length=2048)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        title = value.strip()
        if not title:
            raise ValueError("Название ссылки не должно быть пустым.")
        return title

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        url = value.strip()
        parsed = urlsplit(url)
        try:
            parsed.port
        except ValueError as error:
            raise ValueError("Ссылка должна быть корректным HTTPS-адресом.") from error
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("Ссылка должна быть корректным HTTPS-адресом.")
        return url


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
    review_links: list[GameReviewLink] = Field(default_factory=list)


class GameReviewsUpdateIn(BaseModel):
    links: list[GameReviewLink] = Field(max_length=30)

    @field_validator("links")
    @classmethod
    def deduplicate_links(cls, links: list[GameReviewLink]) -> list[GameReviewLink]:
        unique: list[GameReviewLink] = []
        seen: set[str] = set()
        for link in links:
            key = link.url.casefold()
            if key not in seen:
                seen.add(key)
                unique.append(link)
        return unique


class GameReviewsUpdateOut(BaseModel):
    game_id: int
    links: list[GameReviewLink]


class GameIGDBRefreshIn(BaseModel):
    igdb_id: str | None = Field(default=None, max_length=32)
    igdb_url: str | None = Field(default=None, max_length=2048)

    @field_validator("igdb_id")
    @classmethod
    def validate_igdb_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized.isdigit():
            raise ValueError("IGDB ID должен состоять из цифр.")
        return normalized

    @field_validator("igdb_url")
    @classmethod
    def normalize_igdb_url(cls, value: str | None) -> str | None:
        return value.strip() if value else None

    @model_validator(mode="after")
    def require_one_reference(self) -> "GameIGDBRefreshIn":
        if bool(self.igdb_id) == bool(self.igdb_url):
            raise ValueError("Укажите IGDB ID или ссылку на игру в IGDB.")
        return self


class GameIGDBRefreshOut(BaseModel):
    game_id: int
    igdb_id: str
    igdb_name: str
    message: str


class CurrentStreamGame(BaseModel):
    """Игра из активного стрима либо ожидающей агрегации завершённой сессии."""

    key: str
    stream_id: int
    game_id: int | None = None
    name: str
    duration_minutes: int
    steam_url: str | None = None
    cover_url: str | None = None
    is_live: bool
    started_at: datetime
    first_played_at: datetime
    ended_at: datetime | None = None
    game: GameView | None = None


class GameDetail(GameView):
    genres: list[str]
    platforms: list[str]
    igdb_id: Optional[str] = None
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
