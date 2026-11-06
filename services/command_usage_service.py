"""
Command usage service: sync bot_commands from the in-memory registry
and log every successful command invocation to command_usage_logs.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import BotCommand, BotCommandAlias, CommandUsageLog, User
from services.command_registry import COMMANDS_INFO

logger = logging.getLogger(__name__)


async def ensure_bot_commands(session: AsyncSession) -> None:
    """UPSERT every registered command and its aliases into bot_commands / bot_command_aliases."""
    for name, info in COMMANDS_INFO.items():
        result = await session.execute(select(BotCommand).where(BotCommand.name == name))
        cmd = result.scalar_one_or_none()

        if cmd is None:
            cmd = BotCommand(
                name=name,
                description=info["description"],
                created_at=_utcnow(),
                bot_name="self",
                is_active=True,
                is_visible=True,
            )
            session.add(cmd)
            await session.flush()

        for alias in info.get("aliases", []):
            result = await session.execute(
                select(BotCommandAlias).where(BotCommandAlias.alias == alias)
            )
            if result.scalar_one_or_none() is None:
                session.add(BotCommandAlias(command_id=cmd.id, alias=alias))

    await session.commit()


async def log_command_usage(
    session: AsyncSession,
    user: User,
    streamer: User,
    command_name: str,
    *,
    stream_id: int | None = None,
    invoked_name: str | None = None,
    twitch_message_id: str | None = None,
    created_at=None,
) -> None:
    """Insert a row into command_usage_logs.

    `invoked_name` — алиас, которым фактически вызвали команду; `stream_id` —
    стрим, во время которого это произошло; `twitch_message_id` связывает
    запись с `chat_messages`.
    """
    result = await session.execute(select(BotCommand).where(BotCommand.name == command_name))
    cmd = result.scalar_one_or_none()

    if cmd is None:
        logger.warning("Command %r not found in bot_commands, skipping log", command_name)
        return

    session.add(
        CommandUsageLog(
            user_id=user.id,
            streamer_id=streamer.id,
            command_id=cmd.id,
            stream_id=stream_id,
            invoked_name=invoked_name or command_name,
            twitch_message_id=twitch_message_id,
            created_at=created_at or _utcnow(),
        )
    )
    await session.flush()
