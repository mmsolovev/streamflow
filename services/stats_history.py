"""История изменений статистики и откат батчами.

Каждая запись в `game_stats` / `streams` / `stream_games`, сделанная
пайплайном, проходит через один батч (`stats_change_batches`) и набор
построчных записей (`stats_change_log`). Батч знает источник (`runtime`,
`twitchtracker`, `manual`, `rollback`) и стрим/сессию, к которым относится.

Зачем: TT и runtime могут расходиться, а ручная правка не должна теряться.
Откат (только CLI) читает лог батча в обратном порядке и возвращает значения,
если текущее поле всё ещё равно записанному `new_value`. Более поздние
изменения не перетираются — они попадают в отчёт о пропусках.

Значения в логе хранятся текстом: `None` → SQL NULL, datetime → ISO 8601,
числа → `str`. Обратное преобразование делает `parse_value` по типу колонки.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import StatsChangeBatch, StatsChangeLog

ENTITY_GAME_STATS = "game_stats"
ENTITY_STREAM = "stream"
ENTITY_STREAM_GAME = "stream_game"

SOURCE_RUNTIME = "runtime"
SOURCE_TWITCHTRACKER = "twitchtracker"
SOURCE_MANUAL = "manual"
SOURCE_ROLLBACK = "rollback"

ACTION_APPLY = "apply"
ACTION_ROLLBACK = "rollback"

STATUS_APPLIED = "applied"
STATUS_PARTIALLY_REVERTED = "partially_reverted"
STATUS_REVERTED = "reverted"


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ============================================================
# VALUE SERIALIZATION
# ============================================================


def serialize_value(value: Any) -> str | None:
    """Привести значение ORM-поля к тексту для stats_change_log."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value.isoformat()
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)


def parse_value(raw: str | None, python_type: type | None) -> Any:
    """Обратное преобразование текста лога в значение колонки.

    `python_type` берётся из типа колонки SQLAlchemy
    (`column.type.python_type`). Неизвестный тип — значение остаётся строкой.
    """
    if raw is None:
        return None
    if python_type is datetime:
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None
    if python_type is bool:
        return raw not in ("0", "false", "False", "")
    if python_type is int:
        try:
            return int(raw)
        except (TypeError, ValueError):
            try:
                return int(float(raw))
            except (TypeError, ValueError):
                return None
    if python_type is float:
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None
    return raw


# ============================================================
# BATCHES
# ============================================================


def _new_batch(
    *,
    source: str,
    action: str,
    reason: str | None,
    stream_id: int | None,
    stream_session_id: int | None,
    meta: dict | None,
) -> StatsChangeBatch:
    now = utcnow()
    return StatsChangeBatch(
        source=source,
        action=action,
        reason=reason,
        stream_id=stream_id,
        stream_session_id=stream_session_id,
        status=STATUS_APPLIED,
        changes_count=0,
        created_at=now,
        applied_at=now,
        meta=meta,
    )


async def begin_batch(
    session: AsyncSession,
    *,
    source: str,
    action: str = ACTION_APPLY,
    reason: str | None = None,
    stream_id: int | None = None,
    stream_session_id: int | None = None,
    meta: dict | None = None,
) -> StatsChangeBatch:
    batch = _new_batch(
        source=source,
        action=action,
        reason=reason,
        stream_id=stream_id,
        stream_session_id=stream_session_id,
        meta=meta,
    )
    session.add(batch)
    await session.flush()
    return batch


def record_change(
    session: AsyncSession,
    batch: StatsChangeBatch,
    *,
    entity: str,
    entity_id: int,
    field: str,
    old_value: Any,
    new_value: Any,
    changed_at: datetime | None = None,
) -> StatsChangeLog | None:
    """Записать изменение поля. Возвращает None, если значение не изменилось."""
    old_raw = serialize_value(old_value)
    new_raw = serialize_value(new_value)
    if old_raw == new_raw:
        return None

    entry = StatsChangeLog(
        batch_id=int(batch.id),
        entity=entity,
        entity_id=int(entity_id),
        field=field,
        old_value=old_raw,
        new_value=new_raw,
        changed_at=changed_at or utcnow(),
    )
    session.add(entry)
    batch.changes_count = int(batch.changes_count or 0) + 1
    return entry


async def finalize_batch(
    session: AsyncSession,
    batch: StatsChangeBatch,
    *,
    status: str = STATUS_APPLIED,
) -> StatsChangeBatch:
    batch.status = status
    batch.applied_at = batch.applied_at or utcnow()
    await session.flush()
    return batch


def diff_values(target: Any, updates: dict[str, Any]) -> list[tuple[str, Any, Any]]:
    """Сравнить поля ORM-объекта с желаемыми значениями.

    Возвращает только реально изменившиеся `(field, old, new)`.
    """
    changes: list[tuple[str, Any, Any]] = []
    for field, new_value in updates.items():
        old_value = getattr(target, field, None)
        if serialize_value(old_value) != serialize_value(new_value):
            changes.append((field, old_value, new_value))
    return changes


async def apply_changes(
    session: AsyncSession,
    changes: Iterable[tuple[str, int, str, Any, Any]],
    *,
    source: str,
    action: str = ACTION_APPLY,
    reason: str | None = None,
    stream_id: int | None = None,
    stream_session_id: int | None = None,
    meta: dict | None = None,
) -> StatsChangeBatch | None:
    """Записать список изменений одним батчем.

    `changes` = `(entity, entity_id, field, old_value, new_value)`. Пустой
    список (или все значения совпадают) не создаёт батч — история не
    засоряется пустыми прогонами.
    """
    normalized: list[tuple[str, int, str, Any, Any]] = []
    for entity, entity_id, field, old_value, new_value in changes:
        if serialize_value(old_value) == serialize_value(new_value):
            continue
        normalized.append((entity, entity_id, field, old_value, new_value))

    if not normalized:
        return None

    batch = await begin_batch(
        session,
        source=source,
        action=action,
        reason=reason,
        stream_id=stream_id,
        stream_session_id=stream_session_id,
        meta=meta,
    )
    for entity, entity_id, field, old_value, new_value in normalized:
        record_change(
            session,
            batch,
            entity=entity,
            entity_id=entity_id,
            field=field,
            old_value=old_value,
            new_value=new_value,
        )
    batch.changes_count = len(normalized)
    return await finalize_batch(session, batch)


async def get_batch(
    session: AsyncSession, batch_id: int
) -> StatsChangeBatch | None:
    result = await session.execute(
        select(StatsChangeBatch).where(StatsChangeBatch.id == int(batch_id))
    )
    return result.scalar_one_or_none()


async def load_batch_changes(
    session: AsyncSession, batch_id: int
) -> Sequence[StatsChangeLog]:
    result = await session.execute(
        select(StatsChangeLog)
        .where(StatsChangeLog.batch_id == int(batch_id))
        .order_by(StatsChangeLog.id.desc())
    )
    return list(result.scalars().all())
