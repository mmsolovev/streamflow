"""Games query layer — mirrors sheets_games.py without Google Sheets."""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    Game,
    GameMetadataHLTB,
    GameMetadataIGDB,
    GameStats,
    GameTwitchCategory,
    Genre,
    Platform,
    Stream,
    StreamGame,
    StreamRecording,
    StreamRuntimeSample,
    StreamRuntimeSession,
    StreamStatsJob,
    User,
    UserProfile,
    game_genres,
    game_platforms,
    game_recommendations,
    streamer_games,
)
from backend.repositories._shared import JUST_CHATTING_NAMES, game_recommenders, release_delta_days
from backend.repositories.filters import tag_condition
from backend.repositories.list_query import ListQuery
from backend.repositories.releases import RECENT_RELEASE_DAYS
from config import settings as bot_settings
from pipeline.load.load_recommendations import UPCOMING_RELEASE_LOGIN

_LIGHT_PLATFORMS = {"PC (Microsoft Windows)", "PlayStation 4", "PlayStation 5"}

#: Сколько стримов по игре отдаём сразу на странице игры (остальные — по кнопке).
GAME_STREAMS_PREVIEW = 50


def _runtime_game_durations(
    samples: list[tuple],
    *,
    started_at: datetime,
    ended_at: datetime,
) -> list[dict]:
    """Сложить интервалы по Twitch-категориям, включая повторные заходы в игру."""
    durations: dict[str, dict] = {}
    current_key: str | None = None
    current_start: datetime | None = None
    current_game: dict | None = None
    sample_interval = timedelta(
        seconds=max(int(bot_settings.STREAM_RUNTIME_SAMPLE_SECONDS), 1)
    )

    def add_duration(key: str | None, game: dict | None, start, end) -> None:
        if key is None or game is None or start is None or end <= start:
            return
        entry = durations.setdefault(
            key,
            {
                **game,
                "duration_seconds": 0.0,
            },
        )
        entry["duration_seconds"] += (end - start).total_seconds()
        # Twitch может переименовать категорию с тем же ID — покажем последнее имя.
        entry["category_name"] = game["category_name"]

    for sampled_at, category_name, category_id in samples:
        if not category_name:
            continue
        normalized_id = str(category_id or "").strip() or None
        key = (
            f"id:{normalized_id}"
            if normalized_id
            else f"name:{category_name.casefold()}"
        )
        game = {
            "category_id": normalized_id,
            "category_name": category_name,
            "first_played_at": sampled_at,
        }
        if current_key is None:
            # Первый sample обычно записывается сразу при старте; ограничиваем
            # начальный интервал одним периодом, если коллектор запоздал.
            current_key = key
            current_game = game
            current_start = max(started_at, sampled_at - sample_interval)
        elif key != current_key:
            add_duration(current_key, current_game, current_start, sampled_at)
            current_key = key
            current_game = game
            current_start = sampled_at
        else:
            current_game = game

    add_duration(current_key, current_game, current_start, ended_at)

    result = []
    for key, game in durations.items():
        seconds = game["duration_seconds"]
        result.append(
            {
                "key": key,
                "category_id": game["category_id"],
                "category_name": game["category_name"],
                "first_played_at": game["first_played_at"],
                "duration_minutes": int((seconds + 30) // 60),
            }
        )
    return result


async def list_current_stream_games(session: AsyncSession) -> list[dict]:
    """Игры активного стрима и завершённых сессий до конца runtime-агрегации."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    result = await session.execute(
        select(StreamRuntimeSession, Stream, StreamStatsJob)
        .join(Stream, Stream.id == StreamRuntimeSession.stream_id)
        .outerjoin(
            StreamStatsJob,
            StreamStatsJob.stream_session_id == StreamRuntimeSession.id,
        )
        .where(
            or_(
                StreamRuntimeSession.status == "collecting",
                StreamStatsJob.status.in_(("pending", "processing", "failed")),
            )
        )
        .order_by(StreamRuntimeSession.started_at.desc())
    )
    sessions = result.all()
    if not sessions:
        return []

    eligible = []
    freshness_seconds = max(
        180,
        int(bot_settings.STREAM_RUNTIME_SAMPLE_SECONDS) * 3,
    )
    for runtime_session, stream, job in sessions:
        is_live = runtime_session.status == "collecting"
        if is_live:
            heartbeat = (
                runtime_session.last_sample_at
                or runtime_session.updated_at
                or runtime_session.created_at
                or runtime_session.started_at
            )
            if (
                heartbeat is None
                or (now - heartbeat).total_seconds() > freshness_seconds
                or (heartbeat - now).total_seconds() > 30
            ):
                continue
            ended_at = now
        else:
            # Сюда попадают только сессии с незавершённой задачей агрегации.
            ended_at = runtime_session.ended_at or stream.ended_at
            if ended_at is None:
                continue
        eligible.append((runtime_session, stream, is_live, ended_at))

    if not eligible:
        return []

    session_ids = [int(row[0].id) for row in eligible]
    sample_result = await session.execute(
        select(
            StreamRuntimeSample.stream_session_id,
            StreamRuntimeSample.sampled_at,
            StreamRuntimeSample.category_name,
            StreamRuntimeSample.category_id,
        )
        .where(StreamRuntimeSample.stream_session_id.in_(session_ids))
        .order_by(
            StreamRuntimeSample.stream_session_id,
            StreamRuntimeSample.sampled_at,
        )
    )
    samples_by_session: dict[int, list[tuple]] = {session_id: [] for session_id in session_ids}
    for session_id, sampled_at, category_name, category_id in sample_result.all():
        samples_by_session.setdefault(int(session_id), []).append(
            (sampled_at, category_name, category_id)
        )

    duration_groups: list[tuple[object, object, bool, datetime, list[dict]]] = []
    for runtime_session, stream, is_live, ended_at in eligible:
        games = _runtime_game_durations(
            samples_by_session.get(int(runtime_session.id), []),
            started_at=runtime_session.started_at,
            ended_at=ended_at,
        )
        if games:
            duration_groups.append(
                (runtime_session, stream, is_live, ended_at, games)
            )

    if not duration_groups:
        return []

    category_ids = {
        game["category_id"]
        for _, _, _, _, games in duration_groups
        for game in games
        if game["category_id"]
    }
    category_names = {
        game["category_name"].casefold()
        for _, _, _, _, games in duration_groups
        for game in games
    }
    game_metadata_by_category: dict[str, dict] = {}
    game_metadata_by_name: dict[str, dict] = {}

    if category_ids:
        mapped_rows = await session.execute(
            select(
                GameTwitchCategory.twitch_category_id,
                Game.id,
                Game.name,
                GameMetadataIGDB.steam_url,
                GameMetadataIGDB.cover_url,
            )
            .join(Game, Game.id == GameTwitchCategory.game_id)
            .outerjoin(GameMetadataIGDB, GameMetadataIGDB.game_id == Game.id)
            .where(GameTwitchCategory.twitch_category_id.in_(category_ids))
        )
        for category_id, game_id, name, steam_url, cover_url in mapped_rows.all():
            game_metadata_by_category[str(category_id)] = {
                "game_id": int(game_id),
                "name": name,
                "steam_url": steam_url,
                "cover_url": cover_url,
            }

    missing_ids = category_ids - set(game_metadata_by_category)
    fallback_conditions = []
    if missing_ids:
        fallback_conditions.append(Game.twitch_category_id.in_(missing_ids))
    if category_names:
        fallback_conditions.append(func.lower(Game.name).in_(category_names))
    if fallback_conditions:
        fallback_rows = await session.execute(
            select(
                Game.id,
                Game.name,
                Game.twitch_category_id,
                GameMetadataIGDB.steam_url,
                GameMetadataIGDB.cover_url,
            )
            .outerjoin(GameMetadataIGDB, GameMetadataIGDB.game_id == Game.id)
            .where(or_(*fallback_conditions))
        )
        for game_id, name, twitch_category_id, steam_url, cover_url in fallback_rows.all():
            metadata = {
                "game_id": int(game_id),
                "name": name,
                "steam_url": steam_url,
                "cover_url": cover_url,
            }
            if twitch_category_id:
                game_metadata_by_category.setdefault(str(twitch_category_id), metadata)
            game_metadata_by_name.setdefault(name.casefold(), metadata)

    items_by_game: dict[str, dict] = {}
    for runtime_session, stream, is_live, ended_at, games in duration_groups:
        for game in games:
            metadata = (
                game_metadata_by_category.get(game["category_id"])
                if game["category_id"]
                else None
            ) or game_metadata_by_name.get(game["category_name"].casefold())
            game_id = metadata["game_id"] if metadata else None
            name = metadata["name"] if metadata else game["category_name"]
            key = (
                f"game:{game_id}"
                if game_id is not None
                else f"name:{name.casefold()}"
            )
            item = items_by_game.get(key)
            if item is None:
                items_by_game[key] = {
                    "key": key,
                    "stream_id": int(stream.id),
                    "game_id": game_id,
                    "name": name,
                    "duration_minutes": game["duration_minutes"],
                    "steam_url": metadata["steam_url"] if metadata else None,
                    "cover_url": metadata["cover_url"] if metadata else None,
                    "is_live": is_live,
                    "started_at": runtime_session.started_at,
                    "first_played_at": game["first_played_at"],
                    "ended_at": None if is_live else ended_at,
                }
                continue

            item["duration_minutes"] += game["duration_minutes"]
            if runtime_session.started_at > item["started_at"]:
                item.update(
                    stream_id=int(stream.id),
                    started_at=runtime_session.started_at,
                    first_played_at=game["first_played_at"],
                    ended_at=None if is_live else ended_at,
                )
            item["is_live"] = item["is_live"] or is_live
            if item["is_live"]:
                item["ended_at"] = None

    return sorted(
        items_by_game.values(),
        key=lambda item: item["first_played_at"],
        reverse=True,
    )


async def _flags_map(session: AsyncSession, streamer_id: int, game_ids: list[int]) -> dict[int, tuple[bool, bool]]:
    if not game_ids:
        return {}
    result = await session.execute(
        select(streamer_games).where(
            streamer_games.c.streamer_id == streamer_id,
            streamer_games.c.game_id.in_(game_ids),
        )
    )
    return {
        row.game_id: (bool(row.liked), bool(row.completed))
        for row in result.all()
    }


async def _game_streams(
    session: AsyncSession, game_id: int, *, limit: int | None = None, offset: int = 0
) -> tuple[list[dict], int]:
    """Стримы, на которых играли в игру (от новейших к самым старым)."""
    count_q = select(func.count()).select_from(StreamGame).where(
        StreamGame.game_id == game_id
    )
    total = int((await session.execute(count_q)).scalar_one() or 0)

    q = (
        select(
            Stream.id,
            Stream.started_at,
            Stream.duration_minutes,
            Stream.title,
        )
        .join(StreamGame, StreamGame.stream_id == Stream.id)
        .where(StreamGame.game_id == game_id)
        .order_by(Stream.started_at.desc(), Stream.id.desc())
        .offset(offset)
    )
    if limit is not None:
        q = q.limit(limit)
    rows = (await session.execute(q)).all()
    if not rows:
        return [], total

    vods = (
        await session.execute(
            select(StreamRecording.stream_id, StreamRecording.url)
            .where(
                StreamRecording.stream_id.in_([row[0] for row in rows]),
                StreamRecording.source == "twitch",
                StreamRecording.is_available.is_(True),
            )
            .order_by(StreamRecording.id.asc())
        )
    ).all()
    vod_map: dict[int, str] = {}
    for stream_id, url in vods:
        vod_map.setdefault(stream_id, url)

    return (
        [
            {
                "id": row[0],
                "started_at": row[1],
                "duration_minutes": row[2],
                "title": row[3] or "",
                "vod_url": vod_map.get(row[0]),
            }
            for row in rows
        ],
        total,
    )


async def _is_interested(session: AsyncSession, streamer_id: int, game_id: int) -> bool:
    """Отметка «Интересно» из листа «РЕЛИЗЫ»."""
    result = await session.execute(
        select(streamer_games.c.interested).where(
            streamer_games.c.streamer_id == streamer_id,
            streamer_games.c.game_id == game_id,
        )
    )
    return bool(result.scalar_one_or_none() or False)


async def _user_recommendations_count(session: AsyncSession, game_id: int) -> int:
    """Число рекомендаций без псевдопользователя Twitch (как в листе «Советы»)."""
    twitch_ids = (
        select(User.id)
        .join(UserProfile, UserProfile.user_id == User.id)
        .where(
            UserProfile.login == UPCOMING_RELEASE_LOGIN,
            UserProfile.is_current.is_(True),
        )
        .scalar_subquery()
    )
    result = await session.execute(
        select(func.count())
        .select_from(game_recommendations)
        .where(
            game_recommendations.c.game_id == game_id,
            game_recommendations.c.user_id.notin_(twitch_ids),
        )
    )
    return int(result.scalar_one() or 0)


def _sheets_presence(
    *,
    has_streams: bool,
    has_recommendations: bool,
    has_user_recommendations: bool,
    release_date,
) -> tuple[bool, bool, bool]:
    """В каких листах «Статистики» присутствует игра.

    Условия те же, что и у соответствующих списков:

    * «Игры» — игра была на стримах;
    * «Релизы» — есть рекомендация, а релиз ещё не прошёл (или вышел недавно,
      в пределах `RECENT_RELEASE_DAYS`), либо дата релиза неизвестна;
    * «Советы» — есть рекомендация (без псевдопользователя Twitch), а релиз
      уже состоялся.
    """
    now = datetime.utcnow()
    recent_cutoff = datetime.combine(
        now.date() - timedelta(days=RECENT_RELEASE_DAYS - 1), time.min
    )
    in_games = has_streams
    in_releases = has_recommendations and (
        release_date is None or release_date >= recent_cutoff
    )
    in_recommendations = (
        has_user_recommendations
        and release_date is not None
        and release_date <= now
    )
    return in_games, in_releases, in_recommendations


async def _tags_map(session: AsyncSession, game_ids: list[int]) -> dict[int, str]:
    result = {}
    if not game_ids:
        return result
    ids = list(game_ids)

    genres_result = await session.execute(
        select(game_genres.c.game_id, func.coalesce(Genre.abbreviation, Genre.name))
        .join(Genre, Genre.id == game_genres.c.genre_id)
        .where(game_genres.c.game_id.in_(ids))
    )
    genres_by_game: dict[int, list[str]] = {gid: [] for gid in ids}
    for game_id, value in genres_result.all():
        if value and value not in JUST_CHATTING_NAMES:
            genres_by_game.setdefault(game_id, []).append(value)

    platforms_result = await session.execute(
        select(game_platforms.c.game_id, func.coalesce(Platform.abbreviation, Platform.name))
        .join(Platform, Platform.id == game_platforms.c.platform_id)
        .where(
            game_platforms.c.game_id.in_(ids),
            or_(
                Platform.name.in_(_LIGHT_PLATFORMS),
                Platform.abbreviation.in_({"PC", "PS4", "PS5"}),
            ),
        )
        .order_by(Platform.name)
    )
    platforms_by_game: dict[int, list[str]] = {gid: [] for gid in ids}
    for game_id, value in platforms_result.all():
        platforms_by_game.setdefault(game_id, []).append(value)

    for game_id in ids:
        parts = [
            part for part in [", ".join(platforms_by_game.get(game_id, [])), ", ".join(genres_by_game.get(game_id, []))] if part
        ]
        result[game_id] = " | ".join(parts)
    return result


def _rank_and_order(items: list[dict]) -> list[dict]:
    items.sort(key=lambda r: (-(r["duration_minutes"] or 0), r["name"].casefold()))
    for rank, row in enumerate(items, start=1):
        row["rank"] = rank
    items.sort(
        key=lambda r: (
            r["last_stream"] is None,
            -(r["last_stream"].timestamp()) if r["last_stream"] else 0,
            r["name"].casefold(),
        )
    )
    return items


def _ranked_games_subquery():
    """Все игры с рангом по суммарной длительности (как в разделе «Игры»)."""
    counts = (
        select(StreamGame.game_id, func.count().label("streams_count"))
        .group_by(StreamGame.game_id)
        .subquery()
    )
    return (
        select(
            Game.id.label("id"),
            Game.name.label("name"),
            Game.review_links.label("review_links"),
            GameStats.duration_minutes.label("duration_minutes"),
            GameStats.last_stream.label("last_stream"),
            (
                select(StreamGame.stream_id)
                .join(Stream, Stream.id == StreamGame.stream_id)
                .where(StreamGame.game_id == Game.id)
                .order_by(Stream.started_at.desc(), Stream.id.desc())
                .limit(1)
                .correlate(Game)
                .scalar_subquery()
                .label("last_stream_id")
            ),
            counts.c.streams_count.label("streams_count"),
            GameMetadataIGDB.steam_url.label("steam_url"),
            GameMetadataIGDB.cover_url.label("cover_url"),
            GameMetadataHLTB.hltb_all_styles.label("hltb_all_styles"),
            func.row_number()
            .over(
                order_by=(
                    GameStats.duration_minutes.desc().nulls_last(),
                    func.lower(Game.name).asc(),
                    Game.id.asc(),
                )
            )
            .label("rank"),
        )
        .join(counts, counts.c.game_id == Game.id)
        .join(GameStats, GameStats.game_id == Game.id)
        .outerjoin(GameMetadataIGDB, GameMetadataIGDB.game_id == Game.id)
        .outerjoin(GameMetadataHLTB, GameMetadataHLTB.game_id == Game.id)
        .subquery()
    )


async def get_game_list_views(
    session: AsyncSession,
    *,
    streamer_id: int,
    game_ids: list[int],
) -> dict[int, dict]:
    """Игровые строки для current-stream overlays вне текущей страницы списка."""
    ids = list(dict.fromkeys(int(game_id) for game_id in game_ids))
    if not ids:
        return {}

    ranked = _ranked_games_subquery()
    rows = (
        await session.execute(select(ranked).where(ranked.c.id.in_(ids)))
    ).all()
    flags = await _flags_map(session, streamer_id, [row.id for row in rows])
    tags = await _tags_map(session, [row.id for row in rows])

    return {
        row.id: {
            "id": row.id,
            "name": row.name,
            "rank": int(row.rank or 0),
            "streams_count": int(row.streams_count or 0),
            "duration_minutes": row.duration_minutes,
            "last_stream": row.last_stream,
            "last_stream_id": row.last_stream_id,
            "hltb_all_styles": row.hltb_all_styles,
            "steam_url": row.steam_url,
            "cover_url": row.cover_url,
            "liked": flags.get(row.id, (False, False))[0],
            "completed": flags.get(row.id, (False, False))[1],
            "tags": tags.get(row.id, ""),
            "review_links": row.review_links or [],
        }
        for row in rows
    }


async def list_games(
    session: AsyncSession,
    *,
    streamer_id: int,
    limit: int,
    offset: int,
    query: ListQuery | None = None,
) -> tuple[list[dict], int, int, dict[str, int]]:
    """Список игр: поиск, фильтры, сортировка и пагинация выполняются в БД.

    Возвращает `(items, total, total_all, aggregates)`.
    """
    query = query or ListQuery()
    # Ранг считается по всем играм (до поиска и фильтров) — как в «Играх».
    ranked = _ranked_games_subquery()

    total_all = int(
        (await session.execute(select(func.count()).select_from(ranked))).scalar_one()
        or 0
    )

    q = select(ranked)
    condition = query.text_condition((ranked.c.name,))
    if condition is not None:
        q = q.where(condition)

    if query.has("steam"):
        q = q.where(ranked.c.steam_url.is_not(None))
    if query.has("review"):
        q = q.where(func.jsonb_array_length(ranked.c.review_links) > 0)
    if query.has("liked"):
        q = q.where(
            select(streamer_games.c.game_id)
            .where(
                streamer_games.c.streamer_id == streamer_id,
                streamer_games.c.game_id == ranked.c.id,
                streamer_games.c.liked.is_(True),
            )
            .exists()
        )
    if query.has("completed"):
        q = q.where(
            select(streamer_games.c.game_id)
            .where(
                streamer_games.c.streamer_id == streamer_id,
                streamer_games.c.game_id == ranked.c.id,
                streamer_games.c.completed.is_(True),
            )
            .exists()
        )
    tag_cond = tag_condition(ranked.c.id, query.tags)
    if tag_cond is not None:
        q = q.where(tag_cond)

    total = int(
        (await session.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
        or 0
    )

    sort_column = {
        "last": ranked.c.last_stream,
        "name": ranked.c.name,
        "rank": ranked.c.rank,
        "hours": ranked.c.duration_minutes,
        "streams": ranked.c.streams_count,
        "hltb": ranked.c.hltb_all_styles,
    }.get(query.sort or "", ranked.c.last_stream)
    q = q.order_by(
        sort_column.is_(None),
        sort_column.asc() if not query.is_desc else sort_column.desc(),
        ranked.c.name.asc(),
    ).offset(offset).limit(limit)

    rows = (await session.execute(q)).all()
    game_ids = [row.id for row in rows]
    flags = await _flags_map(session, streamer_id, game_ids)
    tags_map = await _tags_map(session, game_ids)

    items = []
    for row in rows:
        liked, completed = flags.get(row.id, (False, False))
        items.append(
            {
                "id": row.id,
                "name": row.name,
                "review_links": row.review_links or [],
                "rank": int(row.rank or 0),
                "streams_count": int(row.streams_count or 0),
                "last_stream": row.last_stream,
                "last_stream_id": row.last_stream_id,
                "duration_minutes": row.duration_minutes,
                "hltb_all_styles": row.hltb_all_styles,
                "steam_url": row.steam_url,
                "cover_url": row.cover_url,
                "liked": liked,
                "completed": completed,
                "tags": tags_map.get(row.id, ""),
            }
        )

    aggregates = await _games_aggregates(session, streamer_id, ranked)
    return items, total, total_all, aggregates


async def _games_aggregates(
    session: AsyncSession, streamer_id: int, ranked
) -> dict[str, int]:
    """Числа для шапки раздела «Игры» (по всем играм)."""
    liked = int(
        (
            await session.execute(
                select(func.count())
                .select_from(ranked)
                .where(
                    select(streamer_games.c.game_id)
                    .where(
                        streamer_games.c.streamer_id == streamer_id,
                        streamer_games.c.game_id == ranked.c.id,
                        streamer_games.c.liked.is_(True),
                    )
                    .exists()
                )
            )
        ).scalar_one()
        or 0
    )
    completed = int(
        (
            await session.execute(
                select(func.count())
                .select_from(ranked)
                .where(
                    select(streamer_games.c.game_id)
                    .where(
                        streamer_games.c.streamer_id == streamer_id,
                        streamer_games.c.game_id == ranked.c.id,
                        streamer_games.c.completed.is_(True),
                    )
                    .exists()
                )
            )
        ).scalar_one()
        or 0
    )
    return {"liked": liked, "completed": completed}


async def list_games_covers(session: AsyncSession) -> list[dict]:
    """Имя → обложка для всех игр (нужно для полосы обложек в «Стримах»)."""
    rows = (
        await session.execute(
            select(Game.id, Game.name, GameMetadataIGDB.cover_url)
            .outerjoin(GameMetadataIGDB, GameMetadataIGDB.game_id == Game.id)
        )
    ).all()
    return [{"id": row[0], "name": row[1], "cover_url": row[2]} for row in rows]


async def list_games_filter_options(session: AsyncSession) -> dict[str, list[str]]:
    """Доступные значения тегов (жанры/платформы) — для меню фильтров."""
    genres = (
        await session.execute(
            select(func.coalesce(Genre.abbreviation, Genre.name))
            .join(game_genres, game_genres.c.genre_id == Genre.id)
            .distinct()
        )
    ).scalars().all()
    platforms = (
        await session.execute(
            select(func.coalesce(Platform.abbreviation, Platform.name))
            .join(game_platforms, game_platforms.c.platform_id == Platform.id)
            .where(
                or_(
                    Platform.name.in_(_LIGHT_PLATFORMS),
                    Platform.abbreviation.in_({"PC", "PS4", "PS5"}),
                )
            )
            .distinct()
        )
    ).scalars().all()

    tags = sorted({value for value in genres if value and value not in JUST_CHATTING_NAMES})
    platform_names = sorted({value.lower() for value in platforms if value})
    return {"tags": tags, "platforms": platform_names}


async def list_game_streams(
    session: AsyncSession, game_id: int, *, limit: int = 50, offset: int = 0
) -> tuple[list[dict], int]:
    """Стримы по игре — постранично (догрузка на странице игры)."""
    return await _game_streams(session, game_id, limit=limit, offset=offset)


async def get_game(
    session: AsyncSession,
    game_id: int,
    *,
    streamer_id: int,
) -> dict | None:
    result = await session.execute(
        select(Game, GameStats)
        .outerjoin(GameStats, GameStats.game_id == Game.id)
        .where(Game.id == game_id)
    )
    row = result.first()
    if not row:
        return None
    game, stats = row.Game, row.GameStats

    igdb = (
        await session.execute(
            select(GameMetadataIGDB).where(GameMetadataIGDB.game_id == game.id)
        )
    ).scalar_one_or_none()
    hltb = (
        await session.execute(
            select(GameMetadataHLTB).where(GameMetadataHLTB.game_id == game.id)
        )
    ).scalar_one_or_none()

    flags = await _flags_map(session, streamer_id, [game.id])
    liked, completed = flags.get(game.id, (False, False))
    tags = (await _tags_map(session, [game.id])).get(game.id, "")

    genres = [
        r[0]
        for r in (
            await session.execute(
                select(func.coalesce(Genre.abbreviation, Genre.name))
                .join(game_genres, game_genres.c.genre_id == Genre.id)
                .where(game_genres.c.game_id == game.id)
            )
        ).all()
        if r[0] and r[0] not in JUST_CHATTING_NAMES
    ]
    platforms = [
        r[0]
        for r in (
            await session.execute(
                select(func.coalesce(Platform.abbreviation, Platform.name))
                .join(game_platforms, game_platforms.c.platform_id == Platform.id)
                .where(game_platforms.c.game_id == game.id)
            )
        ).all()
        if r[0]
    ]

    streams_count_row = await session.execute(
        select(func.count()).where(StreamGame.game_id == game.id)
    )
    streams_count = int(streams_count_row.scalar_one() or 0)
    rank = 0
    if streams_count > 0:
        ranked = _ranked_games_subquery()
        rank = int(
            (
                await session.execute(
                    select(ranked.c.rank).where(ranked.c.id == game.id)
                )
            ).scalar_one_or_none()
            or 0
        )
    recommenders = await game_recommenders(session, game.id)
    user_recommendations = await _user_recommendations_count(session, game.id)
    game_streams, streams_total = await _game_streams(
        session, game.id, limit=GAME_STREAMS_PREVIEW, offset=0
    )
    interested = await _is_interested(session, streamer_id, game.id)
    release_date = igdb.release_date if igdb else None
    in_games, in_releases, in_recommendations = _sheets_presence(
        has_streams=streams_count > 0,
        has_recommendations=bool(recommenders),
        has_user_recommendations=user_recommendations > 0,
        release_date=release_date,
    )

    return {
        "id": game.id,
        "name": game.name,
        "review_links": game.review_links or [],
        "slug": game.slug,
        "game_type": game.game_type,
        "rank": rank,
        "streams_count": streams_count,
        "last_stream": stats.last_stream if stats else None,
        "last_stream_id": game_streams[0]["id"] if game_streams else None,
        "duration_minutes": stats.duration_minutes if stats else 0,
        "hltb_all_styles": hltb.hltb_all_styles if hltb else None,
        "steam_url": igdb.steam_url if igdb else None,
        "cover_url": igdb.cover_url if igdb else None,
        "liked": liked,
        "completed": completed,
        "tags": tags,
        "genres": genres,
        "platforms": platforms,
        "igdb_id": igdb.igdb_id if igdb else None,
        "release_date": release_date,
        "release_delta_days": release_delta_days(release_date),
        "description_ru": igdb.description_ru if igdb else None,
        "description_en": igdb.description_en if igdb else None,
        "recommenders_list": recommenders,
        "recommenders_count": len(recommenders),
        "interested": interested,
        "hltb_id": hltb.hltb_id if hltb else None,
        "hltb_main_story": hltb.hltb_main_story if hltb else None,
        "hltb_main_extra": hltb.hltb_main_extra if hltb else None,
        "hltb_completionist": hltb.hltb_completionist if hltb else None,
        "hltb_coop": hltb.hltb_coop if hltb else None,
        "hltb_multiplayer": hltb.hltb_multiplayer if hltb else None,
        "streams": game_streams,
        "streams_total": streams_total,
        "in_games": in_games,
        "in_releases": in_releases,
        "in_recommendations": in_recommendations,
    }
