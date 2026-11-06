from __future__ import annotations

from datetime import datetime, timezone

from twitchio.ext import commands

from database.db import AsyncSessionLocal
from runtime import repository
from services.command_registry import register_command
from utils.cooldowns import check_cooldown
from utils.delays import human_delay
from utils.time_format import format_duration_compact


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


async def _load_active_session() -> dict | None:
    """Активная runtime-сессия из PostgreSQL (JSON-хранилище больше не используется)."""
    async with AsyncSessionLocal() as db:
        sessions = await repository.get_collecting_sessions(db)
        if not sessions:
            return None
        return await repository.build_session_snapshot(db, sessions[-1])


def _build_time_message(session: dict) -> str | None:
    started_at = _parse_iso(session.get("started_at"))
    if started_at is None:
        return None

    now = datetime.now(timezone.utc)
    stream_seconds = (now - started_at).total_seconds()
    stream_part = format_duration_compact(stream_seconds)

    segments = session.get("game_segments") or []
    if not segments:
        # показываем текущую категорию, если сегментов нет
        category = session.get("category_name") or "?"
        return f"Стрим идет {stream_part} | {category} {stream_part}"

    parts: list[str] = []
    for seg in segments:
        name = seg.get("category_name") or "?"
        seg_start = _parse_iso(seg.get("started_at"))
        seg_end = _parse_iso(seg.get("ended_at")) or now
        if seg_start is None:
            continue
        dur = format_duration_compact((seg_end - seg_start).total_seconds())
        part = f"[{name}] {dur}"
        if parts and parts[-1].startswith(f"[{name}]"):
            # схлопываем дубликаты подряд
            parts[-1] = part
        else:
            parts.append(part)

    if not parts:
        return None

    max_segments = 6
    if len(parts) > max_segments:
        parts = ["..."] + parts[-max_segments:]

    return f"Стрим идет {stream_part} | " + " -> ".join(parts)


def setup(bot):
    register_command(
        "время",
        "Команда: !время — длительность текущего стрима и длительности категорий по ходу стрима",
        "all",
    )

    @commands.command(name="время")
    async def time_command(ctx):
        if not check_cooldown(ctx, "время", 5):
            return

        session = await _load_active_session()
        if not session or session.get("status") != "active":
            await human_delay()
            await ctx.send("Сейчас стрим не идет")
            return

        message = _build_time_message(session)
        if not message:
            await human_delay()
            await ctx.send("Не смог посчитать время стрима damn")
            return

        await human_delay()
        await ctx.send(message)

    bot.add_command(time_command)
