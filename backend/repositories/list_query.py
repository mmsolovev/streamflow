"""Общие параметры списков: поиск, сортировка и фильтры.

Фильтры передаются теми же ключами, что и на фронтенде
(`tag:<значение>`, `rec:<логин>`, плюс ключи колонок вроде `liked`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from sqlalchemy import or_
from sqlalchemy.sql.elements import ColumnElement


@dataclass
class ListQuery:
    """Разобранные параметры запроса списка."""

    search: str | None = None
    sort: str | None = None
    direction: str = "asc"
    filters: list[str] = field(default_factory=list)

    @property
    def is_desc(self) -> bool:
        return self.direction.lower() == "desc"

    def has(self, key: str) -> bool:
        """Включён ли фильтр с таким ключом."""
        return key in self.filters

    @property
    def tags(self) -> list[str]:
        """Значения тегов из фильтров `tag:<значение>`."""
        return [f.split(":", 1)[1] for f in self.filters if f.startswith("tag:")]

    @property
    def recommenders(self) -> list[str]:
        """Логины рекомендовавших из фильтров `rec:<логин>`."""
        return [f.split(":", 1)[1] for f in self.filters if f.startswith("rec:")]

    def text_condition(self, columns: Iterable[ColumnElement]) -> ColumnElement | None:
        """Условие поиска по подстроке (без учёта регистра)."""
        term = (self.search or "").strip()
        if not term:
            return None
        like = f"%{term.lower()}%"
        parts = []
        for column in columns:
            parts.append(column.ilike(like))
        if not parts:
            return None
        return or_(*parts)


def parse_list_query(
    *,
    search: str | None,
    sort: str | None,
    direction: str | None,
    filters: list[str] | None,
    default_direction: str = "asc",
) -> ListQuery:
    """Собирает `ListQuery` из query-параметров запроса."""
    return ListQuery(
        search=search,
        sort=sort,
        direction=(direction or default_direction).lower(),
        filters=[f for f in (filters or []) if f],
    )
