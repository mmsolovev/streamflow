"""Read queries for the Twitch media catalog."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    Clip,
    Game,
    MediaAsset,
    Stream,
    StreamGame,
    StreamRecording,
    StreamRecordingMedia,
    TelegramAnnouncementMedia,
    TelegramAnnouncementVod,
    User,
    UserProfile,
)
from services.media_asset_service import public_asset_url


def _now_utc_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _filter_ids(filters: list[str], prefix: str) -> list[int]:
    ids: list[int] = []
    for item in filters:
        if not item.startswith(prefix):
            continue
        try:
            value = int(item[len(prefix) :])
        except ValueError:
            continue
        if value > 0:
            ids.append(value)
    return list(dict.fromkeys(ids))


async def _recording_preview_urls(
    session: AsyncSession, recording_ids: list[int]
) -> dict[int, str]:
    if not recording_ids:
        return {}
    priorities = {"manual_preview": 0, "telegram_preview": 1, "twitch_preview": 2}
    selected: dict[int, tuple[int, str]] = {}

    direct_result = await session.execute(
        select(StreamRecordingMedia.recording_id, StreamRecordingMedia.role, MediaAsset)
        .join(MediaAsset, MediaAsset.id == StreamRecordingMedia.asset_id)
        .where(StreamRecordingMedia.recording_id.in_(recording_ids))
    )
    for recording_id, role, asset in direct_result.all():
        url = public_asset_url(asset)
        priority = priorities.get(role)
        if url is not None and priority is not None:
            current = selected.get(int(recording_id))
            if current is None or priority < current[0]:
                selected[int(recording_id)] = (priority, url)

    telegram_result = await session.execute(
        select(TelegramAnnouncementVod.recording_id, MediaAsset)
        .join(
            TelegramAnnouncementMedia,
            TelegramAnnouncementMedia.announcement_id
            == TelegramAnnouncementVod.announcement_id,
        )
        .join(MediaAsset, MediaAsset.id == TelegramAnnouncementMedia.asset_id)
        .where(
            TelegramAnnouncementVod.recording_id.in_(recording_ids),
            TelegramAnnouncementMedia.role == "photo",
        )
        .order_by(
            TelegramAnnouncementVod.stream_started_at.desc(),
            TelegramAnnouncementMedia.position,
        )
    )
    for recording_id, asset in telegram_result.all():
        url = public_asset_url(asset)
        key = int(recording_id)
        current = selected.get(key)
        if url is not None and (
            current is None or priorities["telegram_preview"] < current[0]
        ):
            selected[key] = (priorities["telegram_preview"], url)
    return {recording_id: item[1] for recording_id, item in selected.items()}


async def list_recordings(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    search: str | None = None,
    sort: str = "date",
    direction: str = "desc",
    filters: list[str] | None = None,
) -> tuple[list[dict], int, int]:
    selected_filters = filters or []
    conditions = [
        StreamRecording.source == "twitch",
        StreamRecording.is_available.is_(True),
    ]
    if search:
        pattern = f"%{search.strip()}%"
        conditions.append(
            or_(
                StreamRecording.title.ilike(pattern),
                Stream.title.ilike(pattern),
            )
        )
    game_ids = _filter_ids(selected_filters, "game:")
    if game_ids:
        conditions.append(
            select(StreamGame.stream_id)
            .where(
                StreamGame.stream_id == StreamRecording.stream_id,
                StreamGame.game_id.in_(game_ids),
            )
            .exists()
        )

    total_all = int(
        (
            await session.execute(
                select(func.count())
                .select_from(StreamRecording)
                .where(
                    StreamRecording.source == "twitch",
                    StreamRecording.is_available.is_(True),
                )
            )
        ).scalar_one()
        or 0
    )
    total = int(
        (
            await session.execute(
                select(func.count())
                .select_from(StreamRecording)
                .join(Stream, Stream.id == StreamRecording.stream_id)
                .where(*conditions)
            )
        ).scalar_one()
        or 0
    )
    sort_column = {
        "views": StreamRecording.views_count,
        "title": StreamRecording.title,
        "duration": StreamRecording.duration_minutes,
        "date": StreamRecording.recorded_at,
    }.get(sort, StreamRecording.recorded_at)
    order = sort_column.asc() if direction == "asc" else sort_column.desc()
    result = await session.execute(
        select(StreamRecording, Stream.title)
        .join(Stream, Stream.id == StreamRecording.stream_id)
        .where(*conditions)
        .order_by(order.nullslast(), StreamRecording.id.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = result.all()
    if not rows:
        return [], total, total_all

    stream_ids = list({int(recording.stream_id) for recording, _ in rows})
    preview_urls = await _recording_preview_urls(
        session, [int(recording.id) for recording, _ in rows]
    )
    games_result = await session.execute(
        select(StreamGame.stream_id, Game.id, Game.name)
        .join(Game, Game.id == StreamGame.game_id)
        .where(StreamGame.stream_id.in_(stream_ids))
        .order_by(StreamGame.stream_id, StreamGame.started_at)
    )
    games_by_stream: dict[int, list[str]] = {}
    game_refs_by_stream: dict[int, list[dict[str, int | str]]] = {}
    seen_games_by_stream: dict[int, set[int]] = {}
    for stream_id, game_id, game_name in games_result.all():
        stream_key = int(stream_id)
        game_key = int(game_id)
        seen = seen_games_by_stream.setdefault(stream_key, set())
        if game_name and game_key not in seen:
            seen.add(game_key)
            games_by_stream.setdefault(stream_key, []).append(game_name)
            game_refs_by_stream.setdefault(stream_key, []).append(
                {"id": int(game_id), "name": game_name}
            )

    items = [
        {
            "id": int(recording.id),
            "twitch_video_id": recording.twitch_video_id,
            "title": recording.title or stream_title or "Запись Twitch",
            "url": recording.url,
            "thumbnail_url": preview_urls.get(int(recording.id)),
            "recorded_at": recording.recorded_at,
            "duration_minutes": recording.duration_minutes,
            "views_count": recording.views_count,
            "stream_id": int(recording.stream_id),
            "stream_title": stream_title,
            "games": games_by_stream.get(int(recording.stream_id), []),
            "game_refs": game_refs_by_stream.get(int(recording.stream_id), []),
        }
        for recording, stream_title in rows
    ]
    return items, total, total_all


async def list_clips(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    period: str = "week",
    search: str | None = None,
    sort: str = "views",
    direction: str = "desc",
    filters: list[str] | None = None,
) -> tuple[list[dict], int, int]:
    selected_filters = filters or []
    conditions = []
    now = _now_utc_naive()
    period_days = {"day": 1, "week": 7, "month": 30}.get(period)
    if period_days is not None:
        conditions.append(Clip.created_at >= now - timedelta(days=period_days))
    game_ids = _filter_ids(selected_filters, "game:")
    creator_ids = _filter_ids(selected_filters, "creator:")
    stream_ids = _filter_ids(selected_filters, "stream:")
    # The menu permits multiple selections of each type (OR within type,
    # AND between game, creator, and stream constraints).
    if game_ids:
        conditions.append(Clip.game_id.in_(game_ids))
    if creator_ids:
        conditions.append(Clip.creator_user_id.in_(creator_ids))
    if stream_ids:
        conditions.append(Clip.stream_id.in_(stream_ids))
    if search:
        pattern = f"%{search.strip()}%"
        conditions.append(
            or_(
                Clip.title.ilike(pattern),
                Stream.title.ilike(pattern),
                Game.name.ilike(pattern),
                UserProfile.display_name.ilike(pattern),
                UserProfile.login.ilike(pattern),
            )
        )

    total_all = int(
        (await session.execute(select(func.count()).select_from(Clip))).scalar_one()
        or 0
    )
    query = (
        select(Clip)
        .join(Stream, Stream.id == Clip.stream_id)
        .outerjoin(Game, Game.id == Clip.game_id)
        .outerjoin(User, User.id == Clip.creator_user_id)
        .outerjoin(
            UserProfile,
            and_(
                UserProfile.user_id == User.id,
                UserProfile.is_current.is_(True),
            ),
        )
    )
    filtered_query = query.where(*conditions) if conditions else query
    total = int(
        (
            await session.execute(
                select(func.count()).select_from(filtered_query.subquery())
            )
        ).scalar_one()
        or 0
    )
    sort_column = {
        "date": Clip.created_at,
        "title": Clip.title,
        "views": Clip.views_count,
        "duration": Clip.duration_seconds,
    }.get(sort, Clip.views_count)
    order = sort_column.asc() if direction == "asc" else sort_column.desc()
    result = await session.execute(
        select(
            Clip,
            Stream.title.label("stream_title"),
            Game.name.label("game_name"),
            UserProfile.login.label("creator_login"),
            UserProfile.display_name.label("creator_display_name"),
        )
        .join(Stream, Stream.id == Clip.stream_id)
        .outerjoin(Game, Game.id == Clip.game_id)
        .outerjoin(User, User.id == Clip.creator_user_id)
        .outerjoin(
            UserProfile,
            and_(
                UserProfile.user_id == User.id,
                UserProfile.is_current.is_(True),
            ),
        )
        .where(*conditions)
        .order_by(order.nullslast(), Clip.created_at.desc(), Clip.id.desc())
        .offset(offset)
        .limit(limit)
    )
    items = [
        {
            "id": int(clip.id),
            "external_id": clip.external_id,
            "title": clip.title,
            "url": clip.url,
            "thumbnail_url": clip.thumbnail_url,
            "created_at": clip.created_at,
            "duration_seconds": clip.duration_seconds,
            "views_count": clip.views_count,
            "stream_id": int(clip.stream_id),
            "stream_title": stream_title,
            "game_id": int(clip.game_id) if clip.game_id is not None else None,
            "game_name": game_name,
            "creator_user_id": (
                int(clip.creator_user_id)
                if clip.creator_user_id is not None
                else None
            ),
            "creator_login": creator_login,
            "creator_display_name": creator_display_name,
        }
        for clip, stream_title, game_name, creator_login, creator_display_name
        in result.all()
    ]
    return items, total, total_all


async def list_filter_options(
    session: AsyncSession, *, section: str
) -> dict[str, list[dict[str, str]]]:
    """Available game and (for clips) creator filters."""
    games_query = (
        select(Game.id, Game.name)
        .join(StreamGame, StreamGame.game_id == Game.id)
        .join(StreamRecording, StreamRecording.stream_id == StreamGame.stream_id)
        .where(
            StreamRecording.source == "twitch",
            StreamRecording.is_available.is_(True),
        )
        .distinct()
        .order_by(Game.name)
        if section == "recordings"
        else select(Game.id, Game.name)
        .join(Clip, Clip.game_id == Game.id)
        .distinct()
        .order_by(Game.name)
    )
    games_result = await session.execute(games_query)
    games = [
        {"key": f"game:{int(game_id)}", "label": f"Игра: {game_name}"}
        for game_id, game_name in games_result.all()
        if game_name
    ]

    creators: list[dict[str, str]] = []
    streams: list[dict[str, str]] = []
    if section == "clips":
        creator_label = func.coalesce(
            UserProfile.display_name,
            UserProfile.login,
            cast(User.id, String),
        )
        creators_result = await session.execute(
            select(User.id, creator_label)
            .join(Clip, Clip.creator_user_id == User.id)
            .outerjoin(
                UserProfile,
                and_(
                    UserProfile.user_id == User.id,
                    UserProfile.is_current.is_(True),
                ),
            )
            .distinct()
            .order_by(creator_label)
        )
        creators = [
            {"key": f"creator:{int(user_id)}", "label": f"Автор: {display_name}"}
            for user_id, display_name in creators_result.all()
            if display_name
        ]
        streams_result = await session.execute(
            select(Stream.id, Stream.started_at, Stream.title)
            .join(Clip, Clip.stream_id == Stream.id)
            .distinct()
            .order_by(Stream.started_at.desc())
        )
        streams = [
            {
                "key": f"stream:{int(stream_id)}",
                "label": (
                    f"Стрим: {started_at:%d.%m.%Y} — {title or 'без названия'}"
                    if started_at is not None
                    else f"Стрим: {title or 'без названия'}"
                ),
            }
            for stream_id, started_at, title in streams_result.all()
        ]
    return {"games": games, "creators": creators, "streams": streams}
