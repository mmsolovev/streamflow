from __future__ import annotations

"""
Transform helpers for the recommendations domain.

Normalization and status computation here are intentionally pure (no DB access).

AI short description generation is provided via `services.gpt_service` and may perform external I/O.
"""

import re
from datetime import datetime

from typing import TYPE_CHECKING

from services.gpt_service import generate_short_description

if TYPE_CHECKING:
    from database.models import Game


STATUS_UPCOMING = "upcoming"
STATUS_RELEASED = "released"
STATUS_STREAMED = "streamed"


def normalize_user_login(value: str) -> str:
    return " ".join((value or "").casefold().split())


def normalize_recommendation_name(value: str) -> str:
    normalized = " ".join((value or "").casefold().split())
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    return " ".join(normalized.split())


def determine_recommendation_status(
    *,
    release_date: datetime | None,
    matched_game: "Game | None" = None,
    streamer_interested: bool = False,
) -> str:
    # streamer_interested is currently not affecting status; keep the param for call-site compatibility.
    _ = streamer_interested

    if matched_game is not None:
        return STATUS_STREAMED

    if release_date is None:
        return STATUS_RELEASED

    return STATUS_UPCOMING if release_date > datetime.utcnow() else STATUS_RELEASED


__all__ = [
    "STATUS_RELEASED",
    "STATUS_STREAMED",
    "STATUS_UPCOMING",
    "determine_recommendation_status",
    "generate_short_description",
    "normalize_recommendation_name",
    "normalize_user_login",
]
