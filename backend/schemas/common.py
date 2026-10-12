"""Shared DTOs: pagination, error envelope."""
from __future__ import annotations

from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")

Limit = Annotated[int, Field(ge=1, le=500)]
Offset = Annotated[int, Field(ge=0)]


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class ApiError(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    message: str


class ApiErrorEnvelope(BaseModel):
    detail: ApiError