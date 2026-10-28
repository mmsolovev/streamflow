"""Серверные условия для фильтров списков.

Значения фильтров приходят теми же ключами, что и на фронтенде:
`tag:<значение>` (жанр/платформа), `rec:<логин>` (рекомендовавший) и
`participant:<логин>` (участник стрима).
"""
from __future__ import annotations

from sqlalchemy import and_, func, or_, select
from sqlalchemy.sql.elements import ColumnElement

from database.models import (
    Game,
    Genre,
    Platform,
    Stream,
    StreamGame,
    User,
    UserProfile,
    game_genres,
    game_platforms,
    game_recommendations,
    streamers_on_stream,
)
from backend.repositories._shared import JUST_CHATTING_NAMES

#: Платформы, которые попадают в теги (как в `game_tags`).
_LIGHT_PLATFORM_NAMES = {"PC (Microsoft Windows)", "PlayStation 4", "PlayStation 5"}
_LIGHT_PLATFORM_ABBR = {"PC", "PS4", "PS5"}


def _tag_match(game_id_column, value: str) -> ColumnElement:
    """Совпадение тега (жанра или платформы) со значением из фильтра."""
    like = value.strip().lower()
    genre_match = (
        select(game_genres.c.game_id)
        .join(Genre, Genre.id == game_genres.c.genre_id)
        .where(
            game_genres.c.game_id == game_id_column,
            func.lower(func.coalesce(Genre.abbreviation, Genre.name)) == like,
        )
        .exists()
    )
    platform_match = (
        select(game_platforms.c.game_id)
        .join(Platform, Platform.id == game_platforms.c.platform_id)
        .where(
            game_platforms.c.game_id == game_id_column,
            func.lower(func.coalesce(Platform.abbreviation, Platform.name)) == like,
            or_(
                Platform.name.in_(_LIGHT_PLATFORM_NAMES),
                Platform.abbreviation.in_(_LIGHT_PLATFORM_ABBR),
            ),
        )
        .exists()
    )
    return or_(genre_match, platform_match)


def tag_condition(game_id_column, values: list[str]) -> ColumnElement | None:
    """Игра (или релиз/совет) имеет хотя бы один из указанных тегов."""
    if not values:
        return None
    parts = [_tag_match(game_id_column, value) for value in values]
    return and_(*parts) if len(parts) == 1 else or_(*parts)


def recommender_condition(game_id_column, logins: list[str]) -> ColumnElement | None:
    """Есть рекомендация от одного из указанных пользователей."""
    if not logins:
        return None
    user_ids = (
        select(User.id)
        .join(UserProfile, UserProfile.user_id == User.id)
        .where(
            UserProfile.login.in_([login.casefold() for login in logins]),
            UserProfile.is_current.is_(True),
        )
        .scalar_subquery()
    )
    return (
        select(game_recommendations.c.game_id)
        .where(
            game_recommendations.c.game_id == game_id_column,
            game_recommendations.c.user_id.in_(user_ids),
        )
        .exists()
    )


def stream_participant_condition(
    stream_id_column, logins: list[str]
) -> ColumnElement | None:
    """На стриме есть хотя бы один из указанных участников."""
    normalized = [login.strip().casefold() for login in logins if login.strip()]
    if not normalized:
        return None
    return (
        select(streamers_on_stream.c.stream_id)
        .join(User, User.id == streamers_on_stream.c.streamer_id)
        .join(UserProfile, UserProfile.user_id == User.id)
        .where(
            streamers_on_stream.c.stream_id == stream_id_column,
            UserProfile.is_current.is_(True),
            func.lower(UserProfile.login).in_(normalized),
        )
        .exists()
    )


def stream_tag_condition(stream_id_column, values: list[str]) -> ColumnElement | None:
    """Тег стрима (жанр игры, «Общение», «Участники», «IRL»).

    Жанры берутся из игр стрима (как в `_genres_by_game_map`), остальные
    значения — из самих тегов стрима.
    """
    if not values:
        return None
    parts = []
    for value in values:
        like = value.strip().lower()
        if not like:
            continue
        if like == "общение":
            parts.append(_stream_just_chatting_condition(stream_id_column))
        elif like == "участники":
            parts.append(
                select(streamers_on_stream.c.stream_id)
                .where(streamers_on_stream.c.stream_id == stream_id_column)
                .exists()
            )
        elif like == "irl":
            parts.append(
                select(StreamGame.stream_id)
                .where(
                    StreamGame.stream_id == stream_id_column,
                    or_(
                        func.lower(func.coalesce(Stream.title, "")).like("%irl%"),
                        func.lower(func.coalesce(Game.name, "")).like("%irl%"),
                    ),
                )
                .exists()
            )
        else:
            parts.append(_stream_genre_condition(stream_id_column, like))
    if not parts:
        return None
    return and_(*parts) if len(parts) == 1 else or_(*parts)


def _stream_genre_condition(stream_id_column, like: str) -> ColumnElement:
    """В стриме есть игра с жанром, совпадающим со значением фильтра."""
    return (
        select(StreamGame.stream_id)
        .join(game_genres, game_genres.c.game_id == StreamGame.game_id)
        .join(Genre, Genre.id == game_genres.c.genre_id)
        .where(
            StreamGame.stream_id == stream_id_column,
            func.lower(func.coalesce(Genre.abbreviation, Genre.name)) == like,
        )
        .exists()
    )


def _stream_just_chatting_condition(stream_id_column) -> ColumnElement:
    """В стриме есть «Just Chatting» (тег «Общение»)."""
    return (
        select(StreamGame.stream_id)
        .join(Game, Game.id == StreamGame.game_id)
        .where(
            StreamGame.stream_id == stream_id_column,
            func.lower(Game.name).in_([name.lower() for name in JUST_CHATTING_NAMES]),
        )
        .exists()
    )


def _recommender_label(login: str, display_name: str | None) -> str:
    """Подпись рекомендовавшего — как на фронтенде (`recommenderLabel`)."""
    normalized = login.strip().lower()
    if normalized == "tabula":
        return "Tabula"
    if normalized == "twitch":
        return "Twitch"
    return display_name or login


async def filter_options_for_games(
    session: AsyncSession,
    games_query,
    *,
    exclude_twitch: bool = False,
) -> dict:
    """Опции фильтров раздела: теги (жанры/платформы) и рекомендовавшие.

    `games_query` — подзапрос с id игр раздела.
    """
    game_ids = games_query.subquery()

    genres = (
        await session.execute(
            select(func.coalesce(Genre.abbreviation, Genre.name))
            .join(game_genres, game_genres.c.genre_id == Genre.id)
            .join(game_ids, game_ids.c.id == game_genres.c.game_id)
            .distinct()
        )
    ).scalars().all()
    platforms = (
        await session.execute(
            select(func.coalesce(Platform.abbreviation, Platform.name))
            .join(game_platforms, game_platforms.c.platform_id == Platform.id)
            .join(game_ids, game_ids.c.id == game_platforms.c.game_id)
            .where(
                or_(
                    Platform.name.in_(_LIGHT_PLATFORM_NAMES),
                    Platform.abbreviation.in_(_LIGHT_PLATFORM_ABBR),
                )
            )
            .distinct()
        )
    ).scalars().all()

    recommenders_q = (
        select(UserProfile.login, UserProfile.display_name)
        .join(User, User.id == UserProfile.user_id)
        .join(game_recommendations, game_recommendations.c.user_id == User.id)
        .join(game_ids, game_ids.c.id == game_recommendations.c.game_id)
        .where(UserProfile.is_current.is_(True))
        .distinct()
    )
    if exclude_twitch:
        recommenders_q = recommenders_q.where(UserProfile.login != "twitch")
    recommenders = (await session.execute(recommenders_q)).all()

    by_login: dict[str, str] = {}
    for login, display_name in recommenders:
        if not login:
            continue
        key = login.strip().lower()
        if key not in by_login:
            by_login[key] = _recommender_label(login, display_name)

    def _rank(login: str) -> int:
        return 0 if login == "tabula" else 1 if login == "twitch" else 2

    recommender_entries = [
        {"login": login, "label": label}
        for login, label in sorted(
            by_login.items(), key=lambda item: (_rank(item[0]), item[1].lower())
        )
    ]

    return {
        "tags": sorted(
            {value for value in genres if value and value not in JUST_CHATTING_NAMES}
        ),
        "platforms": sorted({value.lower() for value in platforms if value}),
        "recommenders": recommender_entries,
    }
