from __future__ import annotations

"""
Load layer: writes TwitchTracker games-page snapshots.

The source snapshot is stored in `game_metadata_twitchtracker`. Calculated
`game_stats` values are derived from stream-level detail by
`services.stats_aggregation_service.py`.

Расхождения между значениями TT и пересчитанными попадают только в историю
изменений (`stats_change_batches.meta["tt_divergence"]`).
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Game, GameMetadataTwitchTracker, GameStats, StreamGame
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
    rows: list[
        tuple[GameStats, GameMetadataTwitchTracker, TwitchTrackerGameRow, bool, bool]
    ] = []
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

        metadata = await session.get(GameMetadataTwitchTracker, int(game.id))
        metadata_created = metadata is None
        if metadata is None:
            metadata = GameMetadataTwitchTracker(
                game_id=int(game.id),
                synced_at=now,
            )
            session.add(metadata)

        rows.append((game_stats, metadata, data, created, metadata_created))

    aggregates = await stats_aggregation_service.game_aggregates(
        session, desired_game_ids
    )

    divergences: list[dict] = []

    for game_stats, metadata, data, created, metadata_created in rows:
        game_id = int(game_stats.game_id)

        metadata_changed = metadata_created
        for field, new_value in (
            ("rank", data.rank),
            ("hours_streamed", data.hours_streamed),
            ("avg_viewers", data.avg_viewers),
            ("max_viewers", data.max_viewers),
            ("followers_per_hour", data.followers_per_hour),
            ("last_stream", data.last_stream),
        ):
            old_value = getattr(metadata, field, None)
            if stats_history.serialize_value(old_value) != stats_history.serialize_value(
                new_value
            ):
                setattr(metadata, field, new_value)
                metadata_changed = True

        metadata.synced_at = now
        game_stats.synced_at = now
        game_stats.tt_synced_at = now

        aggregate = aggregates.get(game_id) or {}
        tt_minutes = int(round(float(data.hours_streamed or 0) * 60))
        for field, tt_value in (
            ("duration_minutes", tt_minutes),
            ("max_viewers", data.max_viewers),
            ("last_stream", data.last_stream),
            ("avg_viewers", data.avg_viewers),
            ("followers_per_hour", data.followers_per_hour),
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
        elif metadata_changed:
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
        [],
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
