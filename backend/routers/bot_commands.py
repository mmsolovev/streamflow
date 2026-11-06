"""Bot command registry endpoints (`bot_commands`)."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from backend.deps import AdminDep, SessionDep
from backend.repositories import bot_commands as repo
from backend.repositories.list_query import parse_list_query
from backend.schemas.bot_command import (
    BotCommandCreateIn,
    BotCommandStateUpdateIn,
    BotCommandView,
)
from backend.schemas.common import Page
from database.models import BotCommand

router = APIRouter(prefix="/bot-commands", tags=["bot-commands"])


@router.get("", response_model=Page[BotCommandView])
async def list_bot_commands(
    session: SessionDep,
    search: str | None = Query(None, max_length=64),
    sort: str | None = Query(None, max_length=32),
    direction: str | None = Query(None, pattern="^(asc|desc)$"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> Page[BotCommandView]:
    """Список команд из реестра `bot_commands`."""
    query = parse_list_query(search=search, sort=sort, direction=direction, filters=[])
    items, total, total_all, aggregates = await repo.list_bot_commands(
        session, limit=limit, offset=offset, query=query
    )
    return Page[BotCommandView](
        items=[BotCommandView(**item) for item in items],
        total=total,
        total_all=total_all,
        aggregates=aggregates,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=BotCommandView, status_code=status.HTTP_201_CREATED)
async def create_bot_command(
    body: BotCommandCreateIn,
    session: SessionDep,
    _actor: AdminDep,
) -> BotCommandView:
    """Добавляет команду в реестр. Доступно только администраторам."""
    existing = (
        await session.execute(select(BotCommand).where(BotCommand.name == body.name))
    ).scalar_one_or_none()
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "already_exists",
                "message": f"Команда !{body.name} уже есть в реестре.",
            },
        )

    command = BotCommand(
        name=body.name,
        description=body.description,
        created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        bot_name=body.bot_name,
        is_active=True,
        is_visible=True,
    )
    session.add(command)
    await session.flush()
    await session.commit()

    return _to_view(command)


def _to_view(command: BotCommand) -> BotCommandView:
    return BotCommandView(
        id=command.id,
        name=command.name,
        description=command.description,
        bot_name=command.bot_name,
        is_visible=bool(command.is_visible),
        is_active=bool(command.is_active),
    )


@router.patch("/{command_id}", response_model=BotCommandView)
async def update_bot_command_state(
    command_id: int,
    body: BotCommandStateUpdateIn,
    session: SessionDep,
    _actor: AdminDep,
) -> BotCommandView:
    """Переключает видимость/активность команды. Только для администраторов."""
    command = await session.get(BotCommand, command_id)
    if command is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "not_found", "message": "Команда не найдена."},
        )

    if body.is_visible is not None:
        command.is_visible = body.is_visible
    if body.is_active is not None:
        command.is_active = body.is_active
    await session.commit()

    return _to_view(command)
