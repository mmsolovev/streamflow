"""Shared helpers for the web read layer (copies from sheets_utils, no gspread).

Kept deliberately independent from `pipeline.delivery` per the analysis doc.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    Genre,
    Platform,
    User,
    UserProfile,
    game_genres,
    game_platforms,
    game_recommendations,
)


def build_tags_text(platforms_text: str | None = None, genres_text: str | None = None) -> str:
    parts = [platforms_text, genres_text]
    return " | ".join(part for part in parts if part)


# Категория/псевдо-жанр «Just Chatting» в БД хранится как «Общение».
# В теги не попадает: для стримов тег добавляется отдельной логикой, а для
# игр/релизов/советов он дублировал бы само название игры.
JUST_CHATTING_NAMES = {"Just Chatting", "Общение"}


def build_recommenders_text(recommender_data: list[dict]) -> str:
    tabula_present = False
    twitch_present = False
    users: list[str] = []

    for entry in recommender_data or []:
        login = (entry.get("user_login") or "").casefold()
        if login == "tabula":
            tabula_present = True
            continue
        if login == "twitch":
            twitch_present = True
            continue
        display_name = entry.get("display_name")
        if display_name:
            users.append(display_name)

    result: list[str] = []
    if tabula_present:
        result.append("Tabula")
    if twitch_present:
        result.append("Twitch")
    result.extend(users)
    return ", ".join(result)


def build_recommenders_tooltip(recommender_data: list[dict]) -> str:
    parts: list[str] = []
    for entry in recommender_data or []:
        login = (entry.get("user_login") or "").casefold()
        display_name = entry.get("display_name") or entry.get("user_login") or ""
        note = entry.get("recommendation_note") or ""
        if login == "tabula":
            name = "Tabula"
        elif login == "twitch":
            name = "Twitch"
        else:
            name = display_name
        if note:
            parts.append(f"{name}: {note}")
        else:
            parts.append(name)
    if parts:
        return "\n".join(parts)
    return build_recommenders_text(recommender_data)


def release_delta_days(release_date: datetime | None) -> int | None:
    if not release_date:
        return None
    try:
        days = (release_date.date() - datetime.utcnow().date()).days
    except TypeError:
        return None
    if days < 0:
        return None
    return days


def format_duration_hours(duration_minutes: int | None) -> float:
    if not duration_minutes:
        return 0.0
    return round(duration_minutes / 60, 1)


_LIGHT_PLATFORMS = {"PC (Microsoft Windows)", "PlayStation 4", "PlayStation 5"}


async def game_tags(session: AsyncSession, game_id: int) -> tuple[str, str]:
    genres_result = await session.execute(
        select(func.coalesce(Genre.abbreviation, Genre.name))
        .join(game_genres, game_genres.c.genre_id == Genre.id)
        .where(game_genres.c.game_id == game_id)
    )
    genres_text = ", ".join(
        row[0] for row in genres_result.all() if row[0] and row[0] not in JUST_CHATTING_NAMES
    )

    platforms_result = await session.execute(
        select(func.coalesce(Platform.abbreviation, Platform.name))
        .join(game_platforms, game_platforms.c.platform_id == Platform.id)
        .where(
            game_platforms.c.game_id == game_id,
            or_(
                Platform.name.in_(_LIGHT_PLATFORMS),
                Platform.abbreviation.in_({"PC", "PS4", "PS5"}),
            ),
        )
        .order_by(Platform.name)
    )
    platforms_text = ", ".join(row[0] for row in platforms_result.all())
    return platforms_text, genres_text


async def game_recommenders(session: AsyncSession, game_id: int) -> list[dict]:
    result = await session.execute(
        select(
            UserProfile.login,
            UserProfile.display_name,
            game_recommendations.c.recommendation_note,
        )
        .join(User, User.id == UserProfile.user_id)
        .join(game_recommendations, game_recommendations.c.user_id == User.id)
        .where(
            game_recommendations.c.game_id == game_id,
            UserProfile.is_current.is_(True),
        )
    )
    return [
        {
            "user_login": row[0],
            "display_name": row[1],
            "recommendation_note": row[2],
        }
        for row in result.all()
    ]