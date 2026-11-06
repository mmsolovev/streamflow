"""CLI: откат батча изменений статистики.

    python -m pipeline.orchestrator.rollback_stats --batch 42
    python -m pipeline.orchestrator.rollback_stats --stream 123

Откат читает `stats_change_log` батча в обратном порядке (сначала последние
изменения) и возвращает `old_value` только там, где текущее значение всё ещё
равно записанному `new_value`. Более поздние правки не перетираются: по ним
печатается отчёт о пропусках.

Откат — только CLI. HTTP API и админ-UI не делаются намеренно: операция
редкая и должна быть осознанной.
"""

from __future__ import annotations

import argparse
import asyncio
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.db import AsyncSessionLocal
from database.models import (
    GameStats,
    StatsChangeBatch,
    StatsChangeLog,
    Stream,
    StreamGame,
)
from services import stats_history

MODEL_BY_ENTITY = {
    stats_history.ENTITY_GAME_STATS: (GameStats, "game_id"),
    stats_history.ENTITY_STREAM: (Stream, "id"),
    stats_history.ENTITY_STREAM_GAME: (StreamGame, "id"),
}


def _log(message: str) -> None:
    print(message, flush=True)


def _column_python_type(model: type, field: str) -> type | None:
    column = getattr(model, field, None)
    if column is None:
        return None
    try:
        return column.type.python_type
    except (AttributeError, NotImplementedError):
        return None


async def _load_target(
    session: AsyncSession, entry: StatsChangeLog
) -> tuple[Any, type] | None:
    model_info = MODEL_BY_ENTITY.get(entry.entity)
    if model_info is None:
        return None
    model, pk_name = model_info
    target = await session.get(model, int(entry.entity_id))
    if target is None:
        return None
    return target, model


async def _revert_entry(
    session: AsyncSession,
    entry: StatsChangeLog,
    rollback_batch: StatsChangeBatch,
) -> bool:
    loaded = await _load_target(session, entry)
    if loaded is None:
        return False
    target, model = loaded

    current = getattr(target, entry.field, None)
    if stats_history.serialize_value(current) != entry.new_value:
        return False

    python_type = _column_python_type(model, entry.field)
    old_value = stats_history.parse_value(entry.old_value, python_type)
    setattr(target, entry.field, old_value)
    stats_history.record_change(
        session,
        rollback_batch,
        entity=entry.entity,
        entity_id=int(entry.entity_id),
        field=entry.field,
        old_value=current,
        new_value=old_value,
    )
    return True


async def rollback_batch(
    session: AsyncSession, batch: StatsChangeBatch
) -> tuple[int, int]:
    """Откатить один батч. Возвращает (applied, skipped)."""
    entries = await stats_history.load_batch_changes(session, int(batch.id))

    rollback_batch = await stats_history.begin_batch(
        session,
        source=stats_history.SOURCE_ROLLBACK,
        action=stats_history.ACTION_ROLLBACK,
        reason=f"rollback of batch {batch.id}",
        stream_id=batch.stream_id,
        stream_session_id=batch.stream_session_id,
        meta={"rollback_of_batch_id": int(batch.id), "source": batch.source},
    )

    applied = 0
    skipped = 0
    for entry in entries:
        if await _revert_entry(session, entry, rollback_batch):
            applied += 1
        else:
            skipped += 1

    await stats_history.finalize_batch(session, rollback_batch)
    rollback_batch.changes_count = applied

    batch.reverted_by_batch_id = int(rollback_batch.id)
    if skipped == 0 and applied > 0:
        batch.status = stats_history.STATUS_REVERTED
    elif applied > 0:
        batch.status = stats_history.STATUS_PARTIALLY_REVERTED

    await session.flush()
    return applied, skipped


async def _batches_for_stream(
    session: AsyncSession, stream_id: int
) -> list[StatsChangeBatch]:
    result = await session.execute(
        select(StatsChangeBatch)
        .where(
            StatsChangeBatch.stream_id == int(stream_id),
            StatsChangeBatch.action == stats_history.ACTION_APPLY,
            StatsChangeBatch.status != stats_history.STATUS_REVERTED,
        )
        .order_by(StatsChangeBatch.id.desc())
    )
    return list(result.scalars().all())


async def run(args: argparse.Namespace) -> int:
    async with AsyncSessionLocal() as session:
        if args.batch is not None:
            batch = await stats_history.get_batch(session, int(args.batch))
            if batch is None:
                _log(f"Batch {args.batch} not found")
                return 2
            batches = [batch]
        else:
            batches = await _batches_for_stream(session, int(args.stream))
            if not batches:
                _log(f"No applied batches for stream {args.stream}")
                return 0

        total_applied = 0
        total_skipped = 0
        for batch in batches:
            applied, skipped = await rollback_batch(session, batch)
            total_applied += applied
            total_skipped += skipped
            _log(
                f"Batch {batch.id} ({batch.source}, stream {batch.stream_id}): "
                f"applied {applied}, skipped {skipped}, status {batch.status}"
            )

        await session.commit()

    _log(f"Rollback done: applied {total_applied}, skipped {total_skipped}")
    return 0 if total_skipped == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Rollback game_stats history batch")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--batch", type=int, help="stats_change_batches.id")
    group.add_argument("--stream", type=int, help="rollback all applied batches of a stream")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
