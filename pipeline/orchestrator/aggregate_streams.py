"""CLI: догнать отложенную агрегацию `game_stats`.

Примеры:

    python -m pipeline.orchestrator.aggregate_streams --due
    python -m pipeline.orchestrator.aggregate_streams --stream 123
    python -m pipeline.orchestrator.aggregate_streams --all
    python -m pipeline.orchestrator.aggregate_streams --drift

`--due` — один проход воркера (задачи с `check_at <= now`).
`--stream` — пересчитать игры конкретного стрима, независимо от очереди.
`--all` — сверка всех игр, у которых есть детализация.
`--drift` — только показать расхождения, ничего не записывая.
"""

from __future__ import annotations

import argparse
import asyncio

from database.db import AsyncSessionLocal
from runtime import aggregation_jobs
from services import stats_aggregation_service


def _log(message: str) -> None:
    print(message, flush=True)


async def run(args: argparse.Namespace) -> int:
    if args.due:
        processed = await aggregation_jobs.process_due_jobs_once(limit=args.limit)
        _log(f"Processed due jobs: {processed}")
        return 0

    if args.stream is not None:
        async with AsyncSessionLocal() as session:
            batch = await stats_aggregation_service.recompute_stream_game_stats(
                session,
                stream_id=int(args.stream),
                reason="cli_stream",
            )
            await session.commit()
        _log(
            f"Stream {args.stream}: batch={getattr(batch, 'id', None)} "
            f"changes={getattr(batch, 'changes_count', 0)}"
        )
        return 0

    if args.all:
        async with AsyncSessionLocal() as session:
            batch = await stats_aggregation_service.reconcile_game_stats(
                session, reason="cli_all"
            )
            await session.commit()
        _log(
            f"All games: batch={getattr(batch, 'id', None)} "
            f"changes={getattr(batch, 'changes_count', 0)}"
        )
        return 0

    if args.drift:
        async with AsyncSessionLocal() as session:
            drift = await stats_aggregation_service.find_stats_drift(session)
        if not drift:
            _log("No drift between game_stats and stream_games")
            return 0
        _log(f"Drift rows: {len(drift)}")
        for row in drift:
            _log(
                f"  game {row['game_id']}: duration "
                f"{row['stored_duration']} -> {row['computed_duration']}, streams "
                f"{row['stored_streams']} -> {row['computed_streams']}"
            )
        return 1

    _log("Nothing to do: specify --due, --stream, --all or --drift")
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Aggregate game_stats from runtime stream detail"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--due", action="store_true", help="process due queued jobs")
    group.add_argument("--stream", type=int, help="recompute one stream's games")
    group.add_argument("--all", action="store_true", help="reconcile all games")
    group.add_argument("--drift", action="store_true", help="report drift only")
    parser.add_argument("--limit", type=int, default=50, help="jobs per --due run")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    raise SystemExit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
