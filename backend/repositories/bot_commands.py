"""Bot command query layer — реестр `bot_commands`."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.repositories.list_query import ListQuery
from database.models import BotCommand

#: Сортировка: ключ колонки → выражение.
_SORT_COLUMNS = {
    "name": BotCommand.name,
    "description": BotCommand.description,
    "bot": BotCommand.bot_name,
}


async def list_bot_commands(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    query: ListQuery | None = None,
) -> tuple[list[dict], int, int, dict[str, int]]:
    """Команды из `bot_commands`.

    Возвращает `(items, total, total_all, aggregates)`:
    * `total` — строк после поиска;
    * `total_all` — команд вообще (без поиска);
    * `aggregates` — числа для шапки раздела (`total`, `bots`).
    """
    query = query or ListQuery()

    base = select(
        BotCommand.id,
        BotCommand.name,
        BotCommand.description,
        BotCommand.bot_name,
        BotCommand.is_visible,
        BotCommand.is_active,
    )

    total_all = int(
        (await session.execute(select(func.count()).select_from(BotCommand))).scalar_one()
        or 0
    )
    bots = int(
        (
            await session.execute(
                select(func.count(func.distinct(BotCommand.bot_name))).select_from(
                    BotCommand
                )
            )
        ).scalar_one()
        or 0
    )

    condition = query.text_condition(
        (BotCommand.name, BotCommand.description, BotCommand.bot_name)
    )
    count_q = select(func.count()).select_from(BotCommand)
    if condition is not None:
        base = base.where(condition)
        count_q = count_q.where(condition)

    total = int((await session.execute(count_q)).scalar_one() or 0)

    sort_column = _SORT_COLUMNS.get(query.sort or "", BotCommand.name)
    order = sort_column.desc() if query.is_desc else sort_column.asc()
    q = (
        base.order_by(order, BotCommand.name.asc(), BotCommand.id.asc())
        .offset(offset)
        .limit(limit)
    )

    rows = (await session.execute(q)).all()
    items = [
        {
            "id": row[0],
            "name": row[1],
            "description": row[2],
            "bot_name": row[3],
            "is_visible": row[4],
            "is_active": row[5],
        }
        for row in rows
    ]
    return items, total, total_all, {"total": total_all, "bots": bots}
