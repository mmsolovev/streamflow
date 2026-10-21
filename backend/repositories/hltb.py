"""HowLongToBeat query layer — данные из `game_metadata_hltb`."""
from __future__ import annotations

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Game, GameMetadataHLTB
from backend.repositories.list_query import ListQuery

#: Сортировка: ключ колонки → выражение.
_SORT_COLUMNS = {
    "name": Game.name,
    "all": GameMetadataHLTB.hltb_all_styles,
    "story": GameMetadataHLTB.hltb_main_story,
    "extra": GameMetadataHLTB.hltb_main_extra,
    "completionist": GameMetadataHLTB.hltb_completionist,
    "coop": GameMetadataHLTB.hltb_coop,
    "multiplayer": GameMetadataHLTB.hltb_multiplayer,
}


def _has_data():
    """Игры, у которых заполнено хотя бы одно время."""
    return or_(
        GameMetadataHLTB.hltb_all_styles.is_not(None),
        GameMetadataHLTB.hltb_main_story.is_not(None),
        GameMetadataHLTB.hltb_main_extra.is_not(None),
        GameMetadataHLTB.hltb_completionist.is_not(None),
        GameMetadataHLTB.hltb_coop.is_not(None),
        GameMetadataHLTB.hltb_multiplayer.is_not(None),
    )


async def list_hltb(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    query: ListQuery | None = None,
) -> tuple[list[dict], int, int, dict[str, int]]:
    """Игры с данными HowLongToBeat.

    Возвращает `(items, total, total_all, aggregates)`:
    * `total` — строк после поиска;
    * `total_all` — строк вообще (без поиска);
    * `aggregates` — числа для шапки раздела.
    """
    query = query or ListQuery()
    base = (
        select(
            Game.id,
            Game.name,
            GameMetadataHLTB.hltb_id,
            GameMetadataHLTB.hltb_name,
            GameMetadataHLTB.hltb_all_styles,
            GameMetadataHLTB.hltb_main_story,
            GameMetadataHLTB.hltb_main_extra,
            GameMetadataHLTB.hltb_completionist,
            GameMetadataHLTB.hltb_coop,
            GameMetadataHLTB.hltb_multiplayer,
            GameMetadataHLTB.hltb_review_score,
        )
        .join(GameMetadataHLTB, GameMetadataHLTB.game_id == Game.id)
        .where(_has_data())
    )

    count_q = (
        select(func.count())
        .select_from(GameMetadataHLTB)
        .join(Game, Game.id == GameMetadataHLTB.game_id)
        .where(_has_data())
    )
    total_all = int((await session.execute(count_q)).scalar_one() or 0)

    with_time = int(
        (
            await session.execute(
                count_q.where(GameMetadataHLTB.hltb_all_styles.is_not(None))
            )
        ).scalar_one()
        or 0
    )

    q = base
    condition = query.text_condition((Game.name, GameMetadataHLTB.hltb_name))
    if condition is not None:
        q = q.where(condition)

    total = int(
        (
            await session.execute(select(func.count()).select_from(q.subquery()))
        ).scalar_one()
        or 0
    )

    sort_column = _SORT_COLUMNS.get(query.sort or "", GameMetadataHLTB.hltb_all_styles)
    q = q.order_by(
        sort_column.is_(None),
        sort_column.asc() if not query.is_desc else sort_column.desc(),
        Game.name.asc(),
    ).offset(offset).limit(limit)

    rows = (await session.execute(q)).all()
    items = [
        {
            "id": row[0],
            "name": row[1],
            "hltb_id": row[2],
            "hltb_name": row[3],
            "all_styles": row[4],
            "main_story": row[5],
            "main_extra": row[6],
            "completionist": row[7],
            "coop": row[8],
            "multiplayer": row[9],
            "review_score": row[10],
        }
        for row in rows
    ]
    return items, total, total_all, {"total": total_all, "with_time": with_time}
