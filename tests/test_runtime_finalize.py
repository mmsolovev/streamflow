"""Восстановление снимка runtime-сессии из сэмплов.

`runtime.repository` не хранит game_segments/title_history отдельными
таблицами: на финализации они собираются обратно из `stream_runtime_samples`.
Эти функции решают, какие игры и заголовки попадут в `stream_games` и
`stream_titles`, поэтому проверяются без БД.

Запуск:
    .venv\\Scripts\\python.exe -m pytest tests/test_runtime_finalize.py -q
"""

from datetime import datetime, timezone
from types import SimpleNamespace

from runtime.repository import (
    _histories_from_samples,
    _parse_snapshot_dt,
    _round_int,
    _segments_from_samples,
)


def _sample(
    at: str,
    *,
    category_id: str | None = "100",
    category_name: str | None = "Game A",
    title: str | None = "Title",
    source: str = "sampling.loop",
):
    return SimpleNamespace(
        sampled_at=datetime.fromisoformat(at).replace(tzinfo=None),
        category_id=category_id,
        category_name=category_name,
        title=title,
        viewers_source=source,
    )


def test_same_category_does_not_split_and_last_segment_gets_end():
    samples = [
        _sample("2026-01-01T00:00:00+00:00"),
        _sample("2026-01-01T00:10:00+00:00"),
        _sample(
            "2026-01-01T00:20:00+00:00",
            category_id="200",
            category_name="Game B",
        ),
    ]
    ended_at = datetime(2026, 1, 1, 0, 40)

    segments = _segments_from_samples(samples, ended_at)

    assert [s["category_name"] for s in segments] == ["Game A", "Game B"]
    assert segments[0]["started_at"] == "2026-01-01T00:00:00+00:00"
    assert segments[0]["ended_at"] == "2026-01-01T00:20:00+00:00"
    assert segments[1]["started_at"] == "2026-01-01T00:20:00+00:00"
    assert segments[1]["ended_at"] == "2026-01-01T00:40:00+00:00"
    assert segments[1]["category_id"] == "200"


def test_samples_without_category_are_ignored():
    samples = [
        _sample("2026-01-01T00:00:00+00:00"),
        _sample("2026-01-01T00:10:00+00:00", category_id=None, category_name=None),
    ]

    segments = _segments_from_samples(samples, datetime(2026, 1, 1, 0, 20))

    assert len(segments) == 1
    assert segments[0]["ended_at"] == "2026-01-01T00:20:00+00:00"


def test_no_samples_means_no_segments():
    assert _segments_from_samples([], datetime(2026, 1, 1)) == []


def test_only_changes_create_history_rows():
    samples = [
        _sample("2026-01-01T00:00:00+00:00", title="One"),
        _sample("2026-01-01T00:10:00+00:00", title="One"),
        _sample("2026-01-01T00:20:00+00:00", title="Two"),
        _sample(
            "2026-01-01T00:30:00+00:00",
            title="Two",
            category_name="Game B",
            category_id="200",
        ),
    ]

    titles, categories = _histories_from_samples(samples)

    assert [row["title"] for row in titles] == ["One", "Two"]
    assert [row["changed_at"] for row in titles] == [
        "2026-01-01T00:00:00+00:00",
        "2026-01-01T00:20:00+00:00",
    ]
    assert [row["category_name"] for row in categories] == ["Game A", "Game B"]


def test_parse_snapshot_datetime_converts_to_naive_utc():
    parsed = _parse_snapshot_dt("2026-01-01T03:00:00+03:00")

    assert parsed == datetime(2026, 1, 1, 0, 0)
    assert parsed.tzinfo is None


def test_parse_snapshot_datetime_handles_empty_and_invalid():
    assert _parse_snapshot_dt(None) is None
    assert _parse_snapshot_dt("") is None
    assert _parse_snapshot_dt("not-a-date") is None


def test_parse_naive_datetime_stays_naive():
    parsed = _parse_snapshot_dt("2026-01-01T00:00:00")

    assert parsed == datetime(2026, 1, 1, 0, 0)
    assert parsed.tzinfo is None


def test_round_int():
    assert _round_int(100.4) == 100
    assert _round_int(100.6) == 101
    assert _round_int("12.5") == 12
    assert _round_int(None) is None
    assert _round_int("bad") is None
