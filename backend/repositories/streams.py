"""Streams query layer — mirrors sheets_streams.py without Google Sheets."""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database.models import (
    Genre,
    Stream,
    StreamGame,
    StreamRecording,
    User,
    UserProfile,
    game_genres,
    streamers_on_stream,
)
from backend.repositories._shared import JUST_CHATTING_NAMES
from backend.repositories.filters import stream_tag_condition
from backend.repositories.list_query import ListQuery


async def list_streams_filter_options(session: AsyncSession) -> dict[str, list[str]]:
    """Доступные значения тегов стримов — для меню фильтров.

    Теги стримов собираются в Python (жанры игр + особые значения), поэтому
    значения считаются одним проходом по данным.
    """
    q = select(Stream).options(selectinload(Stream.stream_games).selectinload(StreamGame.game))
    streams = (await session.execute(q)).scalars().unique().all()
    stream_ids = [stream.id for stream in streams]
    genres_by_game = await _genres_by_game_map(session, stream_ids)
    participants = await _participants_map(session, stream_ids)

    values: set[str] = set()
    for stream in streams:
        games = [sg.game for sg in stream.stream_games if sg.game]
        game_names = {game.name for game in games}
        genre_names: list[str] = []
        seen: set[str] = set()
        for sg in stream.stream_games:
            for genre in genres_by_game.get(sg.game_id, []):
                if genre and genre not in seen:
                    seen.add(genre)
                    genre_names.append(genre)
        has_just_chatting = bool(game_names & JUST_CHATTING_NAMES)
        has_other_games = bool(game_names) and not (len(game_names) == 1 and has_just_chatting)
        if has_just_chatting and not has_other_games:
            values.add("Общение")
        values.update(genre_names)
        if participants.get(stream.id):
            values.add("Участники")
        if "IRL" in (stream.title or "") or "IRL" in game_names:
            values.add("IRL")

    return {
        "tags": sorted(values, key=lambda value: value.lower()),
        "dates": sorted(
            {
                stream.started_at.date().isoformat()
                for stream in streams
                if stream.started_at
            },
            reverse=True,
        ),
    }


async def list_streams(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    query: ListQuery | None = None,
) -> tuple[list[dict], int, int, dict[str, int]]:
    """Список стримов: поиск, фильтры, сортировка и пагинация выполняются в БД."""
    query = query or ListQuery()
    where = []
    if date_from is not None:
        where.append(Stream.started_at >= date_from)
    if date_to is not None:
        where.append(Stream.started_at < date_to + timedelta(days=1))

    search_condition = query.text_condition((Stream.title,))
    if search_condition is not None:
        where.append(search_condition)
    if query.has("vod"):
        where.append(
            select(StreamRecording.stream_id)
            .where(
                StreamRecording.stream_id == Stream.id,
                StreamRecording.source == "twitch",
            )
            .exists()
        )
    tag_cond = stream_tag_condition(Stream.id, query.tags)
    if tag_cond is not None:
        where.append(tag_cond)

    total_all = int(
        (await session.execute(select(func.count()).select_from(Stream))).scalar_one() or 0
    )
    total = int(
        (
            await session.execute(
                select(func.count()).select_from(Stream).where(*where)
            )
        ).scalar_one()
        or 0
    )

    # Количество игр на стриме — для сортировки по столбцу «Игры».
    games_count = (
        select(func.count())
        .select_from(StreamGame)
        .where(StreamGame.stream_id == Stream.id)
        .scalar_subquery()
    )
    sort_column = {
        "date": Stream.started_at,
        "title": Stream.title,
        "games": games_count,
        "duration": Stream.duration_minutes,
        "participants": Stream.started_at,
    }.get(query.sort or "", Stream.started_at)

    q = (
        select(Stream)
        .options(selectinload(Stream.stream_games).selectinload(StreamGame.game))
        .where(*where)
        .order_by(
            sort_column.asc() if not query.is_desc else sort_column.desc(),
            Stream.id.desc(),
        )
        .offset(offset)
        .limit(limit)
    )
    streams = (await session.execute(q)).scalars().unique().all()
    if not streams:
        return [], total, total_all, {"total": total_all, "with_vod": 0}

    stream_ids = [stream.id for stream in streams]

    participants = await _participants_map(session, stream_ids)
    genres_by_game = await _genres_by_game_map(session, stream_ids)
    vod_by_stream = await _vods_map(session, stream_ids)

    items = []
    for stream in streams:
        games = [sg.game for sg in stream.stream_games if sg.game]
        game_ids = [game.id for game in games]
        game_names = {game.name for game in games}

        genre_names = []
        seen = set()
        for game_id in game_ids:
            for genre in genres_by_game.get(game_id, []):
                if genre and genre not in seen:
                    seen.add(genre)
                    genre_names.append(genre)

        user_names = participants.get(stream.id, [])
        tags = []
        has_just_chatting = bool(game_names & JUST_CHATTING_NAMES)
        has_other_games = bool(game_names) and not (len(game_names) == 1 and has_just_chatting)
        if has_just_chatting and not has_other_games:
            tags.append("Общение")
        if genre_names:
            tags.append(", ".join(genre_names))
        if user_names:
            tags.append("Участники")
        if "IRL" in (stream.title or "") or "IRL" in game_names:
            tags.append("IRL")

        items.append({
            "id": stream.id,
            "started_at": stream.started_at,
            "ended_at": stream.ended_at,
            "duration_minutes": stream.duration_minutes,
            "title": stream.title or "",
            "games": [game.name for game in games],
            "tags": tags,
            "participants": user_names,
            "vod_url": vod_by_stream.get(stream.id),
            "avg_viewers": stream.avg_viewers,
            "max_viewers": stream.max_viewers,
        })

    with_vod = int(
        (
            await session.execute(
                select(func.count())
                .select_from(Stream)
                .where(
                    select(StreamRecording.stream_id)
                    .where(
                        StreamRecording.stream_id == Stream.id,
                        StreamRecording.source == "twitch",
                    )
                    .exists()
                )
            )
        ).scalar_one()
        or 0
    )
    total_minutes = int(
        (
            await session.execute(
                select(func.coalesce(func.sum(Stream.duration_minutes), 0))
            )
        ).scalar_one()
        or 0
    )
    return items, total, total_all, {
        "total": total_all,
        "with_vod": with_vod,
        "total_minutes": total_minutes,
    }


async def get_stream(session: AsyncSession, stream_id: int) -> dict | None:
    result = await session.execute(
        select(Stream)
        .options(selectinload(Stream.stream_games).selectinload(StreamGame.game))
        .where(Stream.id == stream_id)
    )
    stream = result.scalar_one_or_none()
    if not stream:
        return None

    participants = await _participants_map(session, [stream_id])
    genres_by_game = await _genres_by_game_map(session, [stream_id])
    vod_by_stream = await _vods_map(session, [stream_id])

    games = [sg.game for sg in stream.stream_games if sg.game]
    game_ids = [game.id for game in games]
    game_names = {game.name for game in games}

    genre_names = []
    seen = set()
    for game_id in game_ids:
        for genre in genres_by_game.get(game_id, []):
            if genre and genre not in seen:
                seen.add(genre)
                genre_names.append(genre)

    user_names = participants.get(stream.id, [])
    tags = []
    has_just_chatting = bool(game_names & JUST_CHATTING_NAMES)
    has_other_games = bool(game_names) and not (len(game_names) == 1 and has_just_chatting)
    if has_just_chatting and not has_other_games:
        tags.append("Общение")
    if genre_names:
        tags.append(", ".join(genre_names))
    if user_names:
        tags.append("Участники")
    if "IRL" in (stream.title or "") or "IRL" in game_names:
        tags.append("IRL")

    return {
        "id": stream.id,
        "started_at": stream.started_at,
        "ended_at": stream.ended_at,
        "duration_minutes": stream.duration_minutes,
        "title": stream.title or "",
        "games": [game.name for game in games],
        "tags": tags,
        "participants": user_names,
        "vod_url": vod_by_stream.get(stream.id),
        "avg_viewers": stream.avg_viewers,
        "max_viewers": stream.max_viewers,
    }


async def _participants_map(session: AsyncSession, stream_ids: list[int]) -> dict[int, list[str]]:
    if not stream_ids:
        return {}
    result = await session.execute(
        select(streamers_on_stream.c.stream_id, UserProfile.display_name)
        .join(User, User.id == UserProfile.user_id)
        .join(streamers_on_stream, streamers_on_stream.c.streamer_id == User.id)
        .where(
            streamers_on_stream.c.stream_id.in_(stream_ids),
            UserProfile.is_current.is_(True),
        )
    )
    mapping: dict[int, list[str]] = {}
    for stream_id, display_name in result.all():
        if display_name:
            mapping.setdefault(stream_id, []).append(display_name)
    return mapping


async def _genres_by_game_map(session: AsyncSession, stream_ids: list[int]) -> dict[int, list[str]]:
    if not stream_ids:
        return {}
    subq = (
        select(StreamGame.game_id)
        .where(StreamGame.stream_id.in_(stream_ids))
        .subquery()
    )
    result = await session.execute(
        select(subq.c.game_id, Genre.abbreviation, Genre.name)
        .join(game_genres, game_genres.c.game_id == subq.c.game_id)
        .join(Genre, Genre.id == game_genres.c.genre_id)
    )
    mapping: dict[int, list[str]] = {}
    for game_id, abbreviation, name in result.all():
        genre = abbreviation or name
        if not genre or genre in JUST_CHATTING_NAMES:
            continue
        mapping.setdefault(game_id, []).append(genre)
    return mapping


async def _vods_map(session: AsyncSession, stream_ids: list[int]) -> dict[int, str]:
    if not stream_ids:
        return {}
    result = await session.execute(
        select(StreamRecording.stream_id, StreamRecording.url)
        .where(
            StreamRecording.stream_id.in_(stream_ids),
            StreamRecording.source == "twitch",
        )
        .order_by(StreamRecording.id.asc())
    )
    mapping: dict[int, str] = {}
    for stream_id, url in result.all():
        mapping.setdefault(stream_id, url)
    return mapping