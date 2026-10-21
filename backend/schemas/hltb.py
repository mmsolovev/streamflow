"""HLTB DTOs."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class HltbView(BaseModel):
    """Данные HowLongToBeat по игре (таблица `game_metadata_hltb`)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    hltb_id: str | None = None
    hltb_name: str | None = None
    all_styles: float | None = None
    main_story: float | None = None
    main_extra: float | None = None
    completionist: float | None = None
    coop: float | None = None
    multiplayer: float | None = None
    review_score: int | None = None


class HltbLookupIn(BaseModel):
    """Ссылка на HowLongToBeat (или голый id)."""

    url: str


class HltbLookupOut(BaseModel):
    """Предпросмотр найденной игры — до подтверждения добавления."""

    hltb_id: str
    hltb_name: str
    all_styles: float | None = None
    main_story: float | None = None
    main_extra: float | None = None
    completionist: float | None = None
    coop: float | None = None
    multiplayer: float | None = None
    review_score: int | None = None
    #: Игра в базе, к которой относится эта ссылка (None — создадим новую).
    game_id: int | None = None
    game_name: str | None = None
    #: Такая игра уже есть в базе.
    already_added: bool = False


class HltbAddIn(BaseModel):
    """Добавление игры по ссылке HowLongToBeat."""

    url: str
    #: Игра в базе, выбранная админом (None — определить автоматически).
    game_id: int | None = None


class HltbAddOut(BaseModel):
    game_id: int
    game_name: str
    hltb_id: str
    hltb_name: str | None = None
    all_styles: float | None = None
    message: str
