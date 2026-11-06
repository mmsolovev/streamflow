"""Bot command DTOs (`bot_commands` registry)."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BotCommandView(BaseModel):
    """Команда Twitch-бота из реестра `bot_commands`."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    bot_name: str
    is_visible: bool
    is_active: bool


class BotCommandStateUpdateIn(BaseModel):
    """Частичное обновление флагов команды (только администратор)."""

    is_visible: bool | None = None
    is_active: bool | None = None


class BotCommandCreateIn(BaseModel):
    """Новая команда другого бота (ручное добавление в реестр)."""

    name: str = Field(..., min_length=1, max_length=50)
    description: str = Field(..., min_length=1)
    #: `self` — команда основного бота Mishgan; иначе имя внешнего бота.
    bot_name: str = Field("self", max_length=50)

    @field_validator("name")
    @classmethod
    def _normalize_name(cls, value: str) -> str:
        # В реестре имена хранятся без префикса `!`, в нижнем регистре.
        name = value.strip().lstrip("!").strip().lower()
        if not name:
            raise ValueError("Название команды не может быть пустым.")
        return name

    @field_validator("description")
    @classmethod
    def _strip_description(cls, value: str) -> str:
        description = value.strip()
        if not description:
            raise ValueError("Описание не может быть пустым.")
        return description

    @field_validator("bot_name")
    @classmethod
    def _normalize_bot_name(cls, value: str) -> str:
        return value.strip() or "self"
