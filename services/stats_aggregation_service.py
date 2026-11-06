"""Идемпотентный пересчёт `game_stats` из детализации.

`game_stats` — производная таблица:

- `duration_minutes` = `SUM(stream_games.duration_minutes)`
- `streams_count` = `COUNT(DISTINCT stream_games.stream_id)`
- `last_stream` = `MAX(streams.started_at)`
- `max_viewers` = `MAX(stream_games.peak_viewers)`

Runtime и TwitchTracker пишут детализацию (`streams`, `stream_games`), а
агрегат пересчитывается отсюда. Из-за этого повторный прогон даёт те же числа,
а аддитивный инкремент минут больше не нужен.

`avg_viewers` и `followers_per_hour` здесь не трогаются: их владелец —
TwitchTracker (`pipeline/load/load_game_stats.py`), потому что из детализации
эти значения не восстановить.

Каждый прогон, реально изменивший числа, оставляет батч в
`stats_change_batches` / `stats_change_log` (см. `services/stats_history.py`).
Строки `game_stats` блокируются `SELECT ... FOR UPDATE` в порядке `game_id`,
чтобы параллельные воркеры не разъехались.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import GameStats, Stream, StreamGame
from services import stats_history


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _load_aggregates(
    session: AsyncSession, game_ids: list[int]
) -> dict[int, dict]:
    result = await session.execute(
        select(
            StreamGame.game_id,
            func.sum(StreamGame.duration_minutes),
            func.count(func.distinct(StreamGame.stream_id)),
            func.max(Stream.started_at),
            func.max(StreamGame.peak_viewers),
            # Сколько строк детализации не содержит минут/пиков. Legacy-импорт
            # TwitchTracker оставил их NULL: это «нет данных», а не ноль.
            func.count().filter(StreamGame.duration_minutes.is_(None)),
            func.count().filter(StreamGame.peak_viewers.is_(None)),
        )
        .join(Stream, Stream.id == StreamGame.stream_id)
        .where(StreamGame.game_id.in_(game_ids))
        .group_by(StreamGame.game_id)
    )

    aggregates: dict[int, dict] = {}
    for (
        game_id,
        duration,
        streams_count,
        last_stream,
        max_viewers,
        duration_unknown_rows,
        peak_unknown_rows,
    ) in result.all():
        try:
            duration_minutes = int(round(float(duration or 0)))
        except (TypeError, ValueError):
            duration_minutes = 0
        aggregates[int(game_id)] = {
            "duration_minutes": duration_minutes,
            "streams_count": int(streams_count or 0),
            "last_stream": last_stream,
            "max_viewers": max_viewers,
            "duration_unknown_rows": int(duration_unknown_rows or 0),
            "peak_unknown_rows": int(peak_unknown_rows or 0),
        }
    return aggregates


def _empty_aggregate() -> dict:
    return {
        "duration_minutes": 0,
        "streams_count": 0,
        "last_stream": None,
        "max_viewers": None,
        "duration_unknown_rows": 0,
        "peak_unknown_rows": 0,
    }


def build_target_values(row: Any, aggregate: dict) -> dict:
    """Целевые значения `game_stats` без потери исторических данных.

    В старых строках `stream_games.duration_minutes` и `peak_viewers` пусты:
    TwitchTracker раньше писал только агрегат. Если считать NULL нулём, первый
    же пересчёт обнулил бы историю. Поэтому при неполной детализации:

    - `duration_minutes` оставляем как есть (сумма известных строк — только
      нижняя граница);
    - `max_viewers` не уменьшаем, но учитываем новые пики.

    `streams_count` и `last_stream` всегда выводятся из детализации: для них
    NULL не нужен.
    """
    duration_unknown = int(aggregate.get("duration_unknown_rows") or 0)
    peak_unknown = int(aggregate.get("peak_unknown_rows") or 0)

    if duration_unknown:
        stored_duration = getattr(row, "duration_minutes", None)
        duration_minutes = (
            stored_duration
            if stored_duration is not None
            else int(aggregate.get("duration_minutes") or 0)
        )
    else:
        duration_minutes = int(aggregate.get("duration_minutes") or 0)

    computed_peak = aggregate.get("max_viewers")
    if peak_unknown:
        stored_peak = getattr(row, "max_viewers", None)
        if computed_peak is None:
            max_viewers = stored_peak
        elif stored_peak is None:
            max_viewers = computed_peak
        else:
            max_viewers = max(stored_peak, computed_peak)
    else:
        max_viewers = computed_peak

    return {
        "duration_minutes": duration_minutes,
        "streams_count": int(aggregate.get("streams_count") or 0),
        "last_stream": aggregate.get("last_stream"),
        "max_viewers": max_viewers,
    }


async def game_aggregates(
    session: AsyncSession, game_ids: Iterable[int]
) -> dict[int, dict]:
    """Публичный доступ к агрегатам детализации (для сверки/TT-импорта)."""
    ids = sorted({int(gid) for gid in game_ids if gid is not None and int(gid) > 0})
    if not ids:
        return {}
    return await _load_aggregates(session, ids)


async def recompute_game_stats(
    session: AsyncSession,
    game_ids: Iterable[int],
    *,
    source: str = stats_history.SOURCE_RUNTIME,
    reason: str | None = None,
    stream_id: int | None = None,
    stream_session_id: int | None = None,
    mark_runtime_synced: bool | None = None,
) -> stats_history.StatsChangeBatch | None:
    """Пересчитать `game_stats` для указанных игр.

    Возвращает созданный батч истории или None, если значения не изменились.
    `mark_runtime_synced` по умолчанию True для runtime-источника и False для
    TwitchTracker: провенанс пишется только тем, кто реально считал.
    """
    ids = sorted({int(gid) for gid in game_ids if gid is not None and int(gid) > 0})
    if not ids:
        return None

    if mark_runtime_synced is None:
        mark_runtime_synced = source == stats_history.SOURCE_RUNTIME

    now = utcnow()

    # Новые игры: строка game_stats могла ещё не существовать.
    await session.execute(
        pg_insert(GameStats)
        .values([{"game_id": gid, "synced_at": now} for gid in ids])
        .on_conflict_do_nothing(index_elements=["game_id"])
    )

    locked = await session.execute(
        select(GameStats)
        .where(GameStats.game_id.in_(ids))
        .order_by(GameStats.game_id)
        .with_for_update()
    )
    stats_by_game = {int(row.game_id): row for row in locked.scalars().all()}

    aggregates = await _load_aggregates(session, ids)

    changes: list[tuple[str, int, str, object, object]] = []
    for game_id in ids:
        row = stats_by_game.get(game_id)
        if row is None:
            continue
        aggregate = aggregates.get(game_id) or _empty_aggregate()
        target = build_target_values(row, aggregate)
        for field, old_value, new_value in stats_history.diff_values(row, target):
            changes.append(
                (stats_history.ENTITY_GAME_STATS, game_id, field, old_value, new_value)
            )
            # `apply_changes` только пишет историю; значения выставляем здесь,
            # иначе агрегат остаётся прежним, а в журнале уже «применено».
            setattr(row, field, new_value)

    batch = await stats_history.apply_changes(
        session,
        changes,
        source=source,
        reason=reason,
        stream_id=stream_id,
        stream_session_id=stream_session_id,
        meta={"game_ids": ids},
    )

    for game_id in ids:
        row = stats_by_game.get(game_id)
        if row is None:
            continue
        row.synced_at = now
        if mark_runtime_synced:
            row.runtime_synced_at = now
        if batch is not None:
            row.last_change_batch_id = int(batch.id)

    await session.flush()
    return batch


async def stream_game_ids(session: AsyncSession, stream_id: int) -> list[int]:
    result = await session.execute(
        select(StreamGame.game_id)
        .where(StreamGame.stream_id == int(stream_id))
        .distinct()
    )
    return [int(row[0]) for row in result.all() if row[0] is not None]


async def recompute_stream_game_stats(
    session: AsyncSession,
    *,
    stream_id: int,
    stream_session_id: int | None = None,
    source: str = stats_history.SOURCE_RUNTIME,
    reason: str | None = None,
) -> stats_history.StatsChangeBatch | None:
    """Пересчитать агрегат по играм одного стрима."""
    game_ids = await stream_game_ids(session, stream_id)
    return await recompute_game_stats(
        session,
        game_ids,
        source=source,
        reason=reason,
        stream_id=int(stream_id),
        stream_session_id=stream_session_id,
    )


async def reconcile_game_stats(
    session: AsyncSession,
    *,
    source: str = stats_history.SOURCE_RUNTIME,
    reason: str = "reconcile_all",
) -> stats_history.StatsChangeBatch | None:
    """Пересчитать все игры, у которых есть детализация (CLI `--all`)."""
    result = await session.execute(
        select(StreamGame.game_id).distinct().order_by(StreamGame.game_id)
    )
    return await recompute_game_stats(
        session,
        [int(row[0]) for row in result.all() if row[0] is not None],
        source=source,
        reason=reason,
    )


async def find_stats_drift(session: AsyncSession) -> list[dict]:
    """Сверка `game_stats` с детализацией: расхождения для диагностики."""
    result = await session.execute(
        text(
            """
            SELECT gs.game_id,
                   gs.duration_minutes AS stored_duration,
                   COALESCE(agg.duration_minutes, 0) AS computed_duration,
                   gs.streams_count AS stored_streams,
                   COALESCE(agg.streams_count, 0) AS computed_streams
            FROM game_stats gs
            LEFT JOIN (
                SELECT sg.game_id,
                       SUM(COALESCE(sg.duration_minutes, 0))::int AS duration_minutes,
                       COUNT(DISTINCT sg.stream_id) AS streams_count,
                       COUNT(*) FILTER (
                           WHERE sg.duration_minutes IS NULL
                       ) AS unknown_duration_rows
                FROM stream_games sg
                GROUP BY sg.game_id
            ) agg ON agg.game_id = gs.game_id
            WHERE (
                    COALESCE(agg.unknown_duration_rows, 0) = 0
                    AND gs.duration_minutes IS DISTINCT FROM
                        COALESCE(agg.duration_minutes, 0)
                  )
               OR gs.streams_count IS DISTINCT FROM COALESCE(agg.streams_count, 0)
            ORDER BY gs.game_id
            """
        )
    )
    return [
        {
            "game_id": int(row[0]),
            "stored_duration": row[1],
            "computed_duration": row[2],
            "stored_streams": row[3],
            "computed_streams": row[4],
        }
        for row in result.all()
    ]
