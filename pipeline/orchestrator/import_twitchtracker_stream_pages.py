"""Import archived TwitchTracker stream pages into PostgreSQL.

Dry-run is the default. Use ``--apply`` only after reviewing the match report.
The importer never creates games for unmatched categories and never changes
non-NULL stream/game metrics on conflicts; those are reported for review.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from database.db import AsyncSessionLocal
from database.models import (
    Game,
    GameAlias,
    GameTwitchCategory,
    Stream,
    StreamGame,
    StreamTitle,
)
from pipeline.ingest.twitchtracker_parser import (
    StreamGameEntry,
    StreamPageData,
    parse_stream_page_html,
)
from services import stats_aggregation_service, stats_history
from utils.time_utils import tracker_to_utc, utc_to_tracker

_STREAM_FILENAME = re.compile(r"^stream_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2})\.html$")
_GAME_FIELDS = (
    "duration_minutes",
    "avg_viewers",
    "peak_viewers",
    "followers_gained",
)


@dataclass(slots=True)
class PagePlan:
    path: Path
    stream: Stream
    page: StreamPageData
    games: list[tuple[Game, StreamGameEntry]]


@dataclass(slots=True)
class GameIndexes:
    by_id: dict[str, set[int]]
    by_name: dict[str, set[int]]
    by_alias: dict[str, set[int]]
    games_by_id: dict[int, Game]


@dataclass(slots=True)
class Report:
    files: int = 0
    parsed: int = 0
    stream_matched: int = 0
    game_mentions: int = 0
    titles_to_add: int = 0
    stream_fields_to_fill: int = 0
    new_stream_game_rows: int = 0
    game_fields_to_fill: int = 0
    stream_metric_conflicts: int = 0
    game_metric_conflicts: int = 0
    category_id_conflicts: int = 0
    alias_conflicts: int = 0
    duration_mismatch: int = 0
    blockers: list[str] = field(default_factory=list)
    samples: list[str] = field(default_factory=list)
    conflicts_by_field: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    category_ids_to_add: set[tuple[str, int]] = field(default_factory=set)
    aliases_to_add: set[tuple[str, int]] = field(default_factory=set)
    category_id_games: dict[str, set[int]] = field(default_factory=lambda: defaultdict(set))
    game_category_ids: dict[int, set[str]] = field(default_factory=lambda: defaultdict(set))

    def block(self, message: str) -> None:
        self.blockers.append(message)

    def sample(self, message: str) -> None:
        if len(self.samples) < 25:
            self.samples.append(message)


def _normalize_name(value: str | None) -> str:
    value = unicodedata.normalize("NFKC", value or "").casefold()
    value = re.sub(r"[^\w\s]", " ", value)
    return " ".join(value.split())


def _build_indexes(
    games: list[Game],
    aliases: list[GameAlias],
    twitch_categories: list[GameTwitchCategory] | None = None,
) -> GameIndexes:
    by_id: dict[str, set[int]] = defaultdict(set)
    by_name: dict[str, set[int]] = defaultdict(set)
    by_alias: dict[str, set[int]] = defaultdict(set)
    games_by_id = {int(game.id): game for game in games}

    for game in games:
        key = _normalize_name(game.name)
        if key:
            by_name[key].add(int(game.id))
        category_id = str(game.twitch_category_id or "").strip()
        if category_id:
            by_id[category_id].add(int(game.id))

    for category in twitch_categories or []:
        category_id = str(category.twitch_category_id or "").strip()
        if category_id:
            by_id[category_id].add(int(category.game_id))

    for alias in aliases:
        alias_text = _normalize_name(alias.alias)
        stored_key = _normalize_name(alias.normalized_alias)
        for key in {alias_text, stored_key} - {""}:
            by_alias[key].add(int(alias.game_id))

    return GameIndexes(by_id, by_name, by_alias, games_by_id)


def _name_candidates(indexes: GameIndexes, name: str) -> set[int]:
    key = _normalize_name(name)
    return set(indexes.by_name.get(key, set())) | set(indexes.by_alias.get(key, set()))


def _resolve_game(
    indexes: GameIndexes,
    *,
    name: str,
    twitch_game_id: str | None,
    manual_map: dict[str, str],
) -> tuple[Game | None, str | None]:
    name_key = _normalize_name(name)
    mapped_name = manual_map.get(name_key)
    if mapped_name:
        name_candidates = _name_candidates(indexes, mapped_name)
    else:
        name_candidates = _name_candidates(indexes, name)

    id_key = str(twitch_game_id or "").strip()
    id_candidates = set(indexes.by_id.get(id_key, set())) if id_key else set()

    if len(id_candidates) > 1:
        return None, f"ambiguous Twitch category id {id_key!r}"
    if len(name_candidates) > 1:
        return None, f"ambiguous category name {name!r}"
    if id_candidates and name_candidates and id_candidates != name_candidates:
        return None, (
            f"category id {id_key!r} points to game {sorted(id_candidates)}, "
            f"but name {name!r} points to {sorted(name_candidates)}"
        )
    candidates = id_candidates or name_candidates
    if not candidates:
        return None, f"unmatched category {name!r} (id={id_key or 'none'})"
    return indexes.games_by_id[next(iter(candidates))], None


def _merge_duplicate_entries(
    entries: list[StreamGameEntry],
) -> list[StreamGameEntry]:
    """Collapse repeated category cards in one TT page without losing totals."""
    merged: dict[str, dict] = {}
    order: list[str] = []
    for entry in entries:
        key = str(entry.twitch_game_id or "") or _normalize_name(entry.name)
        if key not in merged:
            merged[key] = {
                "name": entry.name,
                "twitch_game_id": entry.twitch_game_id,
                "avg_weighted": entry.avg_viewers * max(entry.duration_minutes, 0),
                "duration": max(entry.duration_minutes, 0),
                "peak": entry.peak_viewers,
                "followers": entry.followers_gained,
            }
            order.append(key)
            continue
        current = merged[key]
        duration = max(entry.duration_minutes, 0)
        current["avg_weighted"] += entry.avg_viewers * duration
        current["duration"] += duration
        current["peak"] = max(current["peak"], entry.peak_viewers)
        current["followers"] += entry.followers_gained

    result: list[StreamGameEntry] = []
    for key in order:
        item = merged[key]
        duration = item["duration"]
        result.append(
            StreamGameEntry(
                name=item["name"],
                twitch_game_id=item["twitch_game_id"],
                avg_viewers=(
                    int(round(item["avg_weighted"] / duration))
                    if duration > 0
                    else 0
                ),
                peak_viewers=item["peak"],
                duration_minutes=duration,
                followers_gained=item["followers"],
            )
        )
    return result


def _merge_resolved_entries(
    entries: list[tuple[Game, StreamGameEntry]],
) -> list[tuple[Game, StreamGameEntry]]:
    """Ensure one page contributes at most one row per canonical game."""
    grouped: dict[int, list[StreamGameEntry]] = defaultdict(list)
    games: dict[int, Game] = {}
    order: list[int] = []
    for game, entry in entries:
        game_id = int(game.id)
        if game_id not in grouped:
            order.append(game_id)
            games[game_id] = game
        grouped[game_id].append(entry)

    result: list[tuple[Game, StreamGameEntry]] = []
    for game_id in order:
        parts = grouped[game_id]
        duration = sum(max(entry.duration_minutes, 0) for entry in parts)
        weighted_viewers = sum(
            entry.avg_viewers * max(entry.duration_minutes, 0) for entry in parts
        )
        category_ids = {str(entry.twitch_game_id) for entry in parts if entry.twitch_game_id}
        merged = StreamGameEntry(
            name=parts[0].name,
            twitch_game_id=next(iter(category_ids)) if len(category_ids) == 1 else None,
            avg_viewers=(
                int(round(weighted_viewers / duration))
                if duration > 0
                else 0
            ),
            peak_viewers=max(entry.peak_viewers for entry in parts),
            duration_minutes=duration,
            followers_gained=sum(entry.followers_gained for entry in parts),
        )
        # Multiple IDs for the same canonical game preserve metrics but never
        # get auto-assigned to the single games.twitch_category_id column.
        result.append((games[game_id], merged))
    return result


def _load_manual_map(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Game map must be a JSON object: {path}")
    return {
        _normalize_name(str(source)): str(target).strip()
        for source, target in raw.items()
        if str(source).strip() and str(target).strip()
    }


def _file_started_at(path: Path) -> datetime:
    match = _STREAM_FILENAME.match(path.name)
    if not match:
        raise ValueError(
            f"Unexpected filename {path.name!r}; expected "
            "stream_YYYY-MM-DD_HH-MM.html"
        )
    local = datetime.strptime(match.group(1), "%Y-%m-%d_%H-%M")
    return tracker_to_utc(local)


def _stream_key(value: datetime) -> str:
    local = utc_to_tracker(value)
    return local.strftime("%Y-%m-%d_%H-%M")


def _same_minute(a: datetime | None, b: datetime | None) -> bool:
    if a is None or b is None:
        return a is b
    return a.replace(second=0, microsecond=0) == b.replace(second=0, microsecond=0)


def _title_started_at(plan: PagePlan, time_value: str, *, initial: bool) -> datetime:
    if initial and time_value.strip() == "0:00":
        return plan.stream.started_at
    parts = time_value.split(":")
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) > 1 else 0
    local_value = plan.page.date.replace(
        hour=hour,
        minute=minute,
        second=0,
        microsecond=0,
    )
    return tracker_to_utc(local_value)


def _title_key(stream_id: int, title: str, started_at: datetime) -> tuple[int, str, datetime]:
    minute = started_at.replace(second=0, microsecond=0)
    return int(stream_id), title, minute


def _load_pages(
    pages_dir: Path,
    streams: list[Stream],
    indexes: GameIndexes,
    manual_map: dict[str, str],
    report: Report,
) -> list[PagePlan]:
    streams_by_key: dict[str, list[Stream]] = defaultdict(list)
    for stream in streams:
        if stream.started_at is not None:
            streams_by_key[_stream_key(stream.started_at)].append(stream)

    files = sorted(pages_dir.glob("stream_*.html"))
    report.files = len(files)
    plans: list[PagePlan] = []

    for path in files:
        try:
            expected_start = _file_started_at(path)
            page = parse_stream_page_html(path)
        except Exception as exc:  # report bad files and continue preflight
            report.block(f"{path.name}: parse error: {exc}")
            continue
        if page is None or page.started_at is None:
            report.block(f"{path.name}: no stream start time in page")
            continue

        report.parsed += 1
        file_key = _stream_key(expected_start)
        candidates = streams_by_key.get(file_key, [])
        if len(candidates) != 1:
            report.block(
                f"{path.name}: expected exactly one DB stream for {file_key}, "
                f"found {len(candidates)}"
            )
            continue
        stream = candidates[0]

        if not _same_minute(page.started_at, expected_start):
            report.block(
                f"{path.name}: page start {page.started_at} does not match "
                f"filename time {expected_start}"
            )
            continue
        if page.date.date() != utc_to_tracker(expected_start).date():
            report.block(
                f"{path.name}: page date {page.date.date()} does not match "
                f"filename date {utc_to_tracker(expected_start).date()}"
            )
            continue

        mapped: list[tuple[Game, StreamGameEntry]] = []
        for entry in _merge_duplicate_entries(page.games):
            report.game_mentions += 1
            game, error = _resolve_game(
                indexes,
                name=entry.name,
                twitch_game_id=entry.twitch_game_id,
                manual_map=manual_map,
            )
            if error or game is None:
                report.block(f"{path.name}: {error}")
                continue
            incoming_id = str(entry.twitch_game_id or "").strip()
            if incoming_id:
                report.category_id_games[incoming_id].add(int(game.id))
                report.game_category_ids[int(game.id)].add(incoming_id)
            if (
                incoming_id
                and game.twitch_category_id
                and str(game.twitch_category_id) != incoming_id
                and incoming_id not in indexes.by_id
            ):
                report.block(
                    f"{path.name}: {entry.name!r} resolves to {game.name!r} by name, "
                    f"but stored Twitch id is {game.twitch_category_id} and page id "
                    f"is {incoming_id}"
                )
            alias_key = _normalize_name(entry.name)
            if alias_key and alias_key != _normalize_name(game.name):
                owners = (
                    indexes.by_alias.get(alias_key, set())
                    | indexes.by_name.get(alias_key, set())
                )
                if owners and owners != {int(game.id)}:
                    report.alias_conflicts += 1
                    report.block(
                        f"{path.name}: TwitchTracker name {entry.name!r} conflicts "
                        f"with game ids {sorted(owners)}"
                    )
                elif not owners:
                    report.aliases_to_add.add((alias_key, int(game.id)))
            mapped.append((game, entry))
        mapped = _merge_resolved_entries(mapped)
        if not page.games:
            report.block(f"{path.name}: no per-game section parsed")

        if page.duration_minutes and mapped:
            detail_minutes = sum(entry.duration_minutes for _, entry in mapped)
            if abs(detail_minutes - page.duration_minutes) > max(
                3, int(page.duration_minutes * 0.02)
            ):
                report.duration_mismatch += 1
                message = (
                    f"{path.name}: stream={page.duration_minutes}m, "
                    f"game detail={detail_minutes}m"
                )
                report.block(message)
                report.sample(message)

        plans.append(PagePlan(path, stream, page, mapped))
        report.stream_matched += 1

    for category_id, game_ids in report.category_id_games.items():
        if len(game_ids) > 1:
            report.category_id_conflicts += 1
            report.block(
                f"Twitch category id {category_id} maps to multiple games "
                f"{sorted(game_ids)} across pages"
            )
            continue
        game_id = next(iter(game_ids))
        game = indexes.games_by_id[game_id]
        if len(report.game_category_ids[game_id]) > 1:
            report.category_id_conflicts += 1
            report.sample(
                f"{game.name} appears with multiple Twitch category IDs "
                f"{sorted(report.game_category_ids[game_id])}; IDs not auto-assigned"
            )
            continue
        if (
            not indexes.by_id.get(category_id)
            and not game.twitch_category_id
        ):
            report.category_ids_to_add.add((category_id, game_id))
    return plans


def _record_conflict(
    report: Report,
    *,
    entity: str,
    stream: Stream,
    game: Game | None,
    field: str,
    existing,
    incoming,
) -> None:
    if entity == "stream":
        report.stream_metric_conflicts += 1
    else:
        report.game_metric_conflicts += 1
    report.conflicts_by_field[f"{entity}.{field}"] += 1
    report.sample(
        f"stream={stream.id}"
        + (f" game={game.name}" if game else "")
        + f" {entity}.{field}: existing={existing!r}, TT={incoming!r}; "
        "kept existing value"
    )


def _preview_conflicts(
    plans: list[PagePlan],
    stream_games_by_stream: dict[int, list[StreamGame]],
    stream_titles: list[StreamTitle],
    report: Report,
) -> None:
    existing_titles = {
        _title_key(int(row.stream_id), row.title, row.started_at)
        for row in stream_titles
    }
    for plan in plans:
        stream = plan.stream
        page = plan.page
        desired_stream = {
            "duration_minutes": page.duration_minutes,
            "avg_viewers": page.avg_viewers,
            "max_viewers": page.peak_viewers,
            "followers_gained": page.followers_gained,
            "title": page.title_changes[0].title if page.title_changes else None,
        }
        for field, incoming in desired_stream.items():
            existing = getattr(stream, field, None)
            if incoming is None:
                continue
            if existing is None:
                report.stream_fields_to_fill += 1
                continue
            if existing == incoming:
                continue
            _record_conflict(
                report,
                entity="stream",
                stream=stream,
                game=None,
                field=field,
                existing=existing,
                incoming=incoming,
            )
        if stream.ended_at is None and page.ended_at is not None:
            report.stream_fields_to_fill += 1

        for index, change in enumerate(page.title_changes):
            initial = index == 0 and change.offset is None
            try:
                started_at = _title_started_at(
                    plan,
                    change.time,
                    initial=initial,
                )
            except (ValueError, IndexError):
                report.block(
                    f"{plan.path.name}: invalid title timestamp {change.time!r}"
                )
                continue
            key = _title_key(int(stream.id), change.title, started_at)
            if key not in existing_titles:
                report.titles_to_add += 1
                existing_titles.add(key)

        rows_by_game: dict[int, list[StreamGame]] = defaultdict(list)
        for row in stream_games_by_stream.get(int(stream.id), []):
            rows_by_game[int(row.game_id)].append(row)
        for game, entry in plan.games:
            existing_rows = rows_by_game.get(int(game.id), [])
            if len(existing_rows) > 1:
                report.block(
                    f"{plan.path.name}: multiple existing stream_games rows for "
                    f"{game.name} (stream_id={stream.id})"
                )
                continue
            if not existing_rows:
                report.new_stream_game_rows += 1
                report.game_fields_to_fill += len(_GAME_FIELDS)
                continue
            existing_row = existing_rows[0]
            for field in _GAME_FIELDS:
                incoming = getattr(entry, field)
                existing = getattr(existing_row, field)
                if existing is None:
                    report.game_fields_to_fill += 1
                    continue
                if existing == incoming:
                    continue
                _record_conflict(
                    report,
                    entity="stream_game",
                    stream=stream,
                    game=game,
                    field=field,
                    existing=existing,
                    incoming=incoming,
                )


def _add_alias_and_category_id(
    session: AsyncSession,
    *,
    game: Game,
    entry: StreamGameEntry,
    indexes: GameIndexes,
    report: Report,
) -> None:
    category_id = str(entry.twitch_game_id or "").strip()
    if category_id:
        owners = indexes.by_id.get(category_id, set())
        if owners and owners != {int(game.id)}:
            report.category_id_conflicts += 1
            report.sample(
                f"category id {category_id} already belongs to games "
                f"{sorted(owners)}, not {game.name}"
            )
        elif owners == {int(game.id)}:
            # Historical Twitch IDs may map to the same IGDB-backed game.
            pass
        elif (
            not owners
            and not game.twitch_category_id
            and (category_id, int(game.id)) in report.category_ids_to_add
        ):
            game.twitch_category_id = category_id
            indexes.by_id[category_id].add(int(game.id))
        elif game.twitch_category_id and str(game.twitch_category_id) != category_id:
            report.category_id_conflicts += 1
            report.sample(
                f"{game.name} has Twitch id {game.twitch_category_id}, "
                f"TT page has {category_id}"
            )

    source_name = entry.name.strip()
    source_key = _normalize_name(source_name)
    canonical_key = _normalize_name(game.name)
    if not source_key or source_key == canonical_key:
        return
    alias_owners = indexes.by_alias.get(source_key, set())
    name_owners = indexes.by_name.get(source_key, set())
    owners = alias_owners | name_owners
    if owners and owners != {int(game.id)}:
        report.alias_conflicts += 1
        report.sample(
            f"TT alias {source_name!r} for {game.name!r} conflicts with "
            f"games {sorted(owners)}"
        )
        return
    if int(game.id) not in alias_owners:
        session.add(
            GameAlias(
                game_id=int(game.id),
                alias=source_name,
                normalized_alias=source_key,
                is_primary=False,
                source="twitchtracker",
                created_at=stats_history.utcnow(),
                updated_at=stats_history.utcnow(),
            )
        )
        indexes.by_alias[source_key].add(int(game.id))


async def _apply_import(
    session: AsyncSession,
    plans: list[PagePlan],
    indexes: GameIndexes,
    report: Report,
) -> tuple[int, int, int, int]:
    change_refs: list[tuple[str, object, str, object, object]] = []
    affected_game_ids: set[int] = set()
    stream_game_rows_by_stream: dict[int, list[StreamGame]] = defaultdict(list)

    stream_ids = [int(plan.stream.id) for plan in plans]
    if stream_ids:
        result = await session.execute(
            select(StreamGame)
            .where(StreamGame.stream_id.in_(stream_ids))
            .order_by(StreamGame.stream_id, StreamGame.position)
        )
        for row in result.scalars().all():
            stream_game_rows_by_stream[int(row.stream_id)].append(row)

    now = stats_history.utcnow()
    existing_titles: set[tuple[int, str, datetime]] = set()
    if stream_ids:
        title_result = await session.execute(
            select(StreamTitle).where(StreamTitle.stream_id.in_(stream_ids))
        )
        existing_titles = {
            _title_key(int(row.stream_id), row.title, row.started_at)
            for row in title_result.scalars().all()
        }
    titles_added = 0
    for plan in plans:
        stream = plan.stream
        page = plan.page
        stream_desired = {
            "duration_minutes": page.duration_minutes,
            "avg_viewers": page.avg_viewers,
            "max_viewers": page.peak_viewers,
            "followers_gained": page.followers_gained,
            "title": page.title_changes[0].title if page.title_changes else None,
        }
        for field, incoming in stream_desired.items():
            old_value = getattr(stream, field, None)
            if old_value is not None or incoming is None:
                continue
            setattr(stream, field, incoming)
            change_refs.append(
                (stats_history.ENTITY_STREAM, stream, field, old_value, incoming)
            )
        if stream.ended_at is None and page.ended_at is not None:
            stream.ended_at = page.ended_at
            change_refs.append(
                (
                    stats_history.ENTITY_STREAM,
                    stream,
                    "ended_at",
                    None,
                    page.ended_at,
                )
            )
        stream.updated_at = now
        for index, change in enumerate(page.title_changes):
            initial = index == 0 and change.offset is None
            try:
                started_at = _title_started_at(
                    plan,
                    change.time,
                    initial=initial,
                )
            except (ValueError, IndexError):
                continue
            title_key = _title_key(int(stream.id), change.title, started_at)
            if title_key in existing_titles:
                continue
            session.add(
                StreamTitle(
                    stream_id=int(stream.id),
                    title=change.title,
                    started_at=started_at,
                    is_initial=initial,
                    created_at=now,
                )
            )
            existing_titles.add(title_key)
            titles_added += 1

        rows = stream_game_rows_by_stream[int(stream.id)]
        by_game: dict[int, list[StreamGame]] = defaultdict(list)
        for row in rows:
            by_game[int(row.game_id)].append(row)

        ordered_rows: list[StreamGame] = []
        imported_game_ids: set[int] = set()
        for position, (game, entry) in enumerate(plan.games):
            game_id = int(game.id)
            imported_game_ids.add(game_id)
            affected_game_ids.add(game_id)
            _add_alias_and_category_id(
                session,
                game=game,
                entry=entry,
                indexes=indexes,
                report=report,
            )
            candidates = by_game.get(game_id, [])
            if len(candidates) > 1:
                # This is also caught by preflight; never guess which record to
                # collapse because those rows may represent runtime segments.
                continue
            if candidates:
                row = candidates[0]
            else:
                row = StreamGame(
                    stream_id=int(stream.id),
                    game_id=game_id,
                    position=max(
                        (int(item.position or 0) for item in rows),
                        default=-1,
                    )
                    + position
                    + 100,
                )
                session.add(row)
                rows.append(row)
                by_game[game_id] = [row]
                for field in _GAME_FIELDS:
                    value = getattr(entry, field)
                    setattr(row, field, value)
                    change_refs.append(
                        (
                            stats_history.ENTITY_STREAM_GAME,
                            row,
                            field,
                            None,
                            value,
                        )
                    )
            if candidates:
                for field in _GAME_FIELDS:
                    old_value = getattr(row, field, None)
                    incoming = getattr(entry, field)
                    if old_value is not None or incoming is None:
                        continue
                    setattr(row, field, incoming)
                    change_refs.append(
                        (
                            stats_history.ENTITY_STREAM_GAME,
                            row,
                            field,
                            old_value,
                            incoming,
                        )
                    )
            ordered_rows.append(row)

        # Preserve DB-only categories but place them after the TT page order.
        ordered_rows.extend(
            row
            for row in rows
            if int(row.game_id) not in imported_game_ids
            and row not in ordered_rows
        )
        if ordered_rows:
            offset = max((int(row.position or 0) for row in rows), default=0)
            offset += len(ordered_rows) + 100
            for index, row in enumerate(ordered_rows):
                row.position = offset + index
            await session.flush()
            for position, row in enumerate(ordered_rows):
                row.position = position

    await session.flush()
    changes = [
        (entity, int(obj.id), field, old_value, new_value)
        for entity, obj, field, old_value, new_value in change_refs
        if obj.id is not None
    ]

    batch_meta = {
        "pages": len(plans),
        "game_ids": sorted(affected_game_ids),
        "conflict_policy": "preserve_existing_non_null",
        "preserved_conflicts": dict(report.conflicts_by_field),
        "duration_mismatch_pages": report.duration_mismatch,
        "category_id_conflicts": report.category_id_conflicts,
    }
    batch = await stats_history.apply_changes(
        session,
        changes,
        source=stats_history.SOURCE_TWITCHTRACKER,
        reason="import_twitchtracker_stream_pages",
        meta=batch_meta,
    )
    if batch is None and (changes or titles_added):
        batch = await stats_history.begin_batch(
            session,
            source=stats_history.SOURCE_TWITCHTRACKER,
            reason="import_twitchtracker_stream_pages",
            meta=batch_meta,
        )
        await stats_history.finalize_batch(session, batch)

    stats_batch = await stats_aggregation_service.recompute_game_stats(
        session,
        affected_game_ids,
        source=stats_history.SOURCE_TWITCHTRACKER,
        reason="import_twitchtracker_stream_pages",
        mark_runtime_synced=False,
    )
    return (
        int(getattr(batch, "changes_count", 0) or 0),
        int(getattr(stats_batch, "changes_count", 0) or 0),
        len(affected_game_ids),
        titles_added,
    )


def _print_report(report: Report, *, apply: bool) -> None:
    print("TwitchTracker import preflight:")
    print(f"  Stream files: {report.files}")
    print(f"  Parsed pages: {report.parsed}")
    print(f"  Matched streams: {report.stream_matched}")
    print(f"  Per-stream game entries: {report.game_mentions}")
    print(f"  Stream title rows to add: {report.titles_to_add}")
    print(f"  Stream fields to fill: {report.stream_fields_to_fill}")
    print(f"  New stream_games rows: {report.new_stream_game_rows}")
    print(f"  Per-game fields to fill: {report.game_fields_to_fill}")
    print(f"  Stream metric conflicts (preserved): {report.stream_metric_conflicts}")
    print(f"  Game metric conflicts (preserved): {report.game_metric_conflicts}")
    for field_name, count in sorted(report.conflicts_by_field.items()):
        print(f"    {field_name}: {count}")
    print(f"  Twitch ID conflicts: {report.category_id_conflicts}")
    print(f"  Alias conflicts: {report.alias_conflicts}")
    print(f"  Twitch category IDs to add: {len(report.category_ids_to_add)}")
    print(f"  TT aliases to add: {len(report.aliases_to_add)}")
    print(f"  Pages with duration mismatch: {report.duration_mismatch}")
    print(f"  Blocking issues: {len(report.blockers or [])}")
    for item in report.blockers[:30]:
        print(f"    BLOCK: {item}")
    for item in report.samples[:25]:
        print(f"    NOTE: {item}")
    if apply:
        print("  Mode: APPLY")
    else:
        print("  Mode: DRY-RUN (no database changes)")


async def run(
    *,
    root: Path | None = None,
    apply: bool = False,
    game_map_path: Path | None = None,
) -> int:
    project_root = root or Path(__file__).resolve().parents[2]
    stream_pages_dir = project_root / "storage" / "pages" / "streams_tt"
    if not stream_pages_dir.exists():
        print(f"Missing TwitchTracker stream pages directory: {stream_pages_dir}")
        return 1

    manual_map = _load_manual_map(game_map_path)
    report = Report()

    async with AsyncSessionLocal() as session:
        games = (await session.execute(select(Game).order_by(Game.id))).scalars().all()
        aliases = (await session.execute(select(GameAlias))).scalars().all()
        twitch_categories = (
            await session.execute(select(GameTwitchCategory))
        ).scalars().all()
        streams = (
            await session.execute(
                select(Stream).where(Stream.started_at.is_not(None)).order_by(Stream.id)
            )
        ).scalars().all()
        indexes = _build_indexes(games, aliases, twitch_categories)

        plans = _load_pages(stream_pages_dir, streams, indexes, manual_map, report)
        matched_stream_ids = {int(plan.stream.id) for plan in plans}
        if len(matched_stream_ids) != len(plans):
            report.block("multiple input files resolved to the same database stream")

        stream_game_rows_by_stream: dict[int, list[StreamGame]] = defaultdict(list)
        stream_titles: list[StreamTitle] = []
        if matched_stream_ids:
            result = await session.execute(
                select(StreamGame)
                .where(StreamGame.stream_id.in_(matched_stream_ids))
                .order_by(StreamGame.stream_id, StreamGame.position)
            )
            for row in result.scalars().all():
                stream_game_rows_by_stream[int(row.stream_id)].append(row)
            title_result = await session.execute(
                select(StreamTitle).where(StreamTitle.stream_id.in_(matched_stream_ids))
            )
            stream_titles = title_result.scalars().all()
        _preview_conflicts(
            plans,
            stream_game_rows_by_stream,
            stream_titles,
            report,
        )
        _print_report(report, apply=apply)

        if not apply:
            await session.rollback()
            return 1 if report.blockers else 0
        if report.blockers:
            print("Import not applied: resolve blocking issues and rerun.")
            await session.rollback()
            return 1

        history_changes, stats_changes, affected_games, titles_added = await _apply_import(
            session, plans, indexes, report
        )
        await session.commit()
        print("Import committed:")
        print(f"  History change rows: {history_changes}")
        print(f"  game_stats changed fields: {stats_changes}")
        print(f"  Games recomputed: {affected_games}")
        print(f"  Stream title rows added: {titles_added}")
        print(
            f"  Identity links added: {len(report.category_ids_to_add)} category IDs, "
            f"{len(report.aliases_to_add)} aliases"
        )
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write accepted data to PostgreSQL (default is dry-run)",
    )
    parser.add_argument(
        "--game-map",
        type=Path,
        help="optional JSON mapping of TwitchTracker category names to canonical game names",
    )
    args = parser.parse_args()
    raise SystemExit(
        asyncio.run(run(apply=args.apply, game_map_path=args.game_map))
    )


if __name__ == "__main__":
    main()
