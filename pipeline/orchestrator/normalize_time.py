"""Нормализация времени TwitchTracker в UTC.

TwitchTracker показывает время канала без зоны, а runtime пишет UTC. Из-за
этого старые строки `streams.started_at/ended_at` и `stream_titles.started_at`
сдвинуты относительно runtime на смещение пояса (`TWITCHTRACKER_TIMEZONE`,
по умолчанию Europe/Moscow, +3).

Скрипт переводит в UTC только строки без runtime-сессии: у них время уже
корректное. Строки, созданные runtime, пропускаются.

Запуск:
    python -m pipeline.orchestrator.normalize_time          # dry-run
    python -m pipeline.orchestrator.normalize_time --apply  # записать
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime

from sqlalchemy import select

from database.db import AsyncSessionLocal
from database.models import Stream, StreamRuntimeSession, StreamTitle
from utils.time_utils import tracker_to_utc


def _format(value: datetime | None) -> str:
    return value.isoformat(sep=" ", timespec="seconds") if value else "-"


async def run(*, apply: bool) -> None:
    async with AsyncSessionLocal() as session:
        runtime_stream_ids = {
            int(row[0])
            for row in (
                await session.execute(select(StreamRuntimeSession.stream_id))
            ).all()
            if row[0] is not None
        }

        streams = (
            await session.execute(select(Stream).order_by(Stream.id.asc()))
        ).scalars().all()

        updated_streams = 0
        updated_titles = 0
        skipped_runtime = 0

        for stream in streams:
            if int(stream.id) in runtime_stream_ids:
                skipped_runtime += 1
                continue
            if stream.started_at is None and stream.ended_at is None:
                continue

            started_utc = tracker_to_utc(stream.started_at)
            ended_utc = tracker_to_utc(stream.ended_at)
            changed = (
                started_utc != stream.started_at or ended_utc != stream.ended_at
            )
            if not changed:
                continue

            updated_streams += 1
            print(
                f"stream {stream.id}: "
                f"{_format(stream.started_at)} -> {_format(started_utc)} .. "
                f"{_format(stream.ended_at)} -> {_format(ended_utc)}"
            )
            if apply:
                stream.started_at = started_utc
                stream.ended_at = ended_utc

            titles = (
                await session.execute(
                    select(StreamTitle).where(StreamTitle.stream_id == stream.id)
                )
            ).scalars().all()
            for title in titles:
                title_utc = tracker_to_utc(title.started_at)
                if title_utc == title.started_at:
                    continue
                updated_titles += 1
                if apply:
                    title.started_at = title_utc

        # Дата последнего стрима в game_stats (`last_stream`) хранится как
        # дата без времени: смещение пояса к ней не применяется.

        if apply:
            await session.commit()
            print(
                f"Applied: streams={updated_streams}, titles={updated_titles}, "
                f"runtime skipped={skipped_runtime}"
            )
        else:
            print(
                f"Dry-run: streams={updated_streams}, titles={updated_titles}, "
                f"runtime skipped={skipped_runtime}. Use --apply to write."
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="записать изменения (по умолчанию только показать)",
    )
    args = parser.parse_args()
    asyncio.run(run(apply=args.apply))


if __name__ == "__main__":
    main()
