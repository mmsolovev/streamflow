from __future__ import annotations

"""
Load layer: writes targeting `game_stats` table (GameStats).

TwitchTracker — единственный источник `avg_viewers` и `followers_per_hour`:
из детализации стримов их не восстановить. Остальные агрегаты
(`duration_minutes`, `max_viewers`, `last_stream`, `streams_count`)
пересчитываются из `stream_games` / `streams` в
`services.stats_aggregation_service.py` и здесь не пишутся.

Расхождения между значениями TT и пересчитанными попадают только в историю
изменений (`stats_change_batches.meta["tt_divergence"]`), чтобы не перетирать
более точную детализацию.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Game, GameStats, StreamGame
from pipeline.ingest.twitchtracker_parser import TwitchTrackerGameRow
from pipeline.load.load_games import get_or_create_game
from services import stats_aggregation_service, stats_history


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@dataclass(frozen=True, slots=True)
class SyncStats:
    added: int = 0
    updated: int = 0
    unchanged: int = 0
    deleted: int = 0
    divergences: int = 0


def _divergence(
    game_id: int, field: str, tt_value, computed_value
) -> dict | None:
    if computed_value is None:
        return None
    if stats_history.serialize_value(tt_value) == stats_history.serialize_value(
        computed_value
    ):
        return None
    return {
        "game_id": int(game_id),
        "field": field,
        "tt_value": stats_history.serialize_value(tt_value),
        "computed_value": stats_history.serialize_value(computed_value),
    }


async def sync_game_stats(
    session: AsyncSession,
    games_data: list[TwitchTrackerGameRow],
    game_cache: dict[str, Game],
    *,
    prune_missing: bool = False,
) -> SyncStats:
    stats = SyncStats()
    desired_game_ids: set[int] = set()

    now = _utcnow()
    rows: list[tuple[GameStats, TwitchTrackerGameRow, bool]] = []
    for data in games_data:
        game = await get_or_create_game(session, game_cache, data.name, source="twitchtracker")
        desired_game_ids.add(int(game.id))

        result = await session.execute(select(GameStats).where(GameStats.game_id == game.id))
        game_stats = result.scalar_one_or_none()
        created = False

        if game_stats is None:
            game_stats = GameStats(game_id=game.id)
            session.add(game_stats)
            await session.flush()
            created = True

        rows.append((game_stats, data, created))

    aggregates = await stats_aggregation_service.game_aggregates(
        session, desired_game_ids
    )

    changes: list[tuple[str, int, str, object, object]] = []
    divergences: list[dict] = []

    for game_stats, data, created in rows:
        game_id = int(game_stats.game_id)

        # Только поля, которыми владеет TwitchTracker.
        for field, new_value in (
            ("avg_viewers", data.avg_viewers),
            ("followers_per_hour", data.followers_per_hour),
        ):
            old_value = getattr(game_stats, field, None)
            if stats_history.serialize_value(old_value) != stats_history.serialize_value(
                new_value
            ):
                changes.append(
                    (stats_history.ENTITY_GAME_STATS, game_id, field, old_value, new_value)
                )
                setattr(game_stats, field, new_value)

        game_stats.synced_at = now
        game_stats.tt_synced_at = now

        aggregate = aggregates.get(game_id) or {}
        tt_minutes = int(round(float(data.hours_streamed or 0) * 60))
        for field, tt_value in (
            ("duration_minutes", tt_minutes),
            ("max_viewers", data.max_viewers),
            ("last_stream", data.last_stream),
        ):
            entry = _divergence(game_id, field, tt_value, aggregate.get(field))
            if entry is not None:
                divergences.append(entry)

        if created:
            stats = SyncStats(
                added=stats.added + 1,
                updated=stats.updated,
                unchanged=stats.unchanged,
                deleted=stats.deleted,
                divergences=stats.divergences,
            )
        elif any(change[1] == game_id for change in changes):
            stats = SyncStats(
                added=stats.added,
                updated=stats.updated + 1,
                unchanged=stats.unchanged,
                deleted=stats.deleted,
                divergences=stats.divergences,
            )
        else:
            stats = SyncStats(
                added=stats.added,
                updated=stats.updated,
                unchanged=stats.unchanged + 1,
                deleted=stats.deleted,
                divergences=stats.divergences,
            )

    meta = {"tt_divergence": divergences} if divergences else None
    batch = await stats_history.apply_changes(
        session,
        changes,
        source=stats_history.SOURCE_TWITCHTRACKER,
        reason="sync_game_stats",
        meta=meta,
    )
    if batch is None and divergences:
        # Изменений в полях TT нет, но расхождения нужно сохранить в истории.
        batch = await stats_history.begin_batch(
            session,
            source=stats_history.SOURCE_TWITCHTRACKER,
            reason="sync_game_stats",
            meta=meta,
        )
        await stats_history.finalize_batch(session, batch)

    if prune_missing:
        # Удалять можно только строки без детализации: `game_stats` теперь
        # производная от `stream_games`, и игра, которой нет в списке TT, но
        # которая есть в runtime-статистике, не должна терять `avg_viewers`.
        deleted = 0
        detail_result = await session.execute(select(StreamGame.game_id).distinct())
        with_detail = {
            int(row[0]) for row in detail_result.all() if row[0] is not None
        }
        result = await session.execute(select(GameStats))
        for row in result.scalars().all():
            game_id = int(row.game_id)
            if game_id in desired_game_ids or game_id in with_detail:
                continue
            await session.delete(row)
            deleted += 1

        if deleted:
            stats = SyncStats(
                added=stats.added,
                updated=stats.updated,
                unchanged=stats.unchanged,
                deleted=stats.deleted + deleted,
                divergences=stats.divergences,
            )

    return SyncStats(
        added=stats.added,
        updated=stats.updated,
        unchanged=stats.unchanged,
        deleted=stats.deleted,
        divergences=len(divergences),
    )


async def update_streams_count(session: AsyncSession) -> int:
    """Пересчитать агрегаты всех игр (legacy-путь JSON-импорта).

    Возвращает число игр с изменёнными полями. Раньше функция трогала только
    `streams_count`; теперь это часть идемпотентного пересчёта.
    """
    result = await session.execute(select(StreamGame.game_id).distinct())
    game_ids = [int(row[0]) for row in result.all() if row[0] is not None]
    batch = await stats_aggregation_service.recompute_game_stats(
        session,
        game_ids,
        source=stats_history.SOURCE_TWITCHTRACKER,
        reason="import_json_update_streams_count",
    )
    return int(getattr(batch, "changes_count", 0) or 0)


__all__ = ["SyncStats", "sync_game_stats", "update_streams_count"]
