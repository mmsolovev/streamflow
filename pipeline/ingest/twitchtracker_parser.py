from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass
from typing import Any

from bs4 import BeautifulSoup


@dataclass(frozen=True, slots=True)
class TwitchTrackerStreamRow:
    date: datetime
    duration_hours: float
    avg_viewers: int
    max_viewers: int
    followers: int
    views: int
    title: str
    games: list[str]


@dataclass(frozen=True, slots=True)
class TwitchTrackerGameRow:
    name: str
    rank: int
    hours_streamed: float
    avg_viewers: int
    max_viewers: int
    followers_per_hour: float
    last_stream: datetime


def parse_stream_date(value: str) -> datetime:
    return datetime.strptime(value, "%d/%b/%Y %H:%M")


def parse_game_last_stream(value: str) -> datetime:
    return datetime.strptime(value, "%d/%b/%Y")


def clean_int(value: Any) -> int:
    return int(str(value).replace(",", "").strip())


def clean_float(value: Any) -> float:
    return float(str(value).replace(",", "").strip())


def clean_duration_hours(value: Any) -> float:
    s = str(value).strip().replace(" ", "")
    if s.lower().endswith("hrs"):
        s = s[: -3]
    return float(s)


def _unique_in_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _stream_date_cell_text(td: Any) -> str:
    span = td.find("span")
    if span:
        return span.get_text(strip=True)
    return td.get_text(strip=True)


def _stream_metric_cell_int(td: Any) -> int:
    span = td.find("span")
    raw = span.get_text(strip=True) if span else td.get_text(strip=True)
    return clean_int(raw)


def _stream_duration_cell_text(td: Any) -> str:
    span = td.find("span")
    raw = span.get_text(strip=True) if span else td.get_text(strip=True)
    return raw.replace(" ", "").replace(" hrs", "hrs")


def _parse_stream_row_cells(cols: list[Any]) -> TwitchTrackerStreamRow | None:
    if len(cols) < 8:
        return None

    date = parse_stream_date(_stream_date_cell_text(cols[0]))
    games: list[str] = []
    for img in cols[7].find_all("img"):
        game_name = img.get("data-original-title")
        if game_name:
            games.append(str(game_name))
    games = _unique_in_order(games)

    return TwitchTrackerStreamRow(
        date=date,
        duration_hours=clean_duration_hours(_stream_duration_cell_text(cols[1])),
        avg_viewers=_stream_metric_cell_int(cols[2]),
        max_viewers=_stream_metric_cell_int(cols[3]),
        followers=_stream_metric_cell_int(cols[4]),
        views=_stream_metric_cell_int(cols[5]),
        title=cols[6].get_text(strip=True),
        games=games,
    )


def _iter_stream_rows_from_soup(soup: BeautifulSoup) -> list[TwitchTrackerStreamRow]:
    table = soup.find("table", id="streams")
    row_els = table.find_all("tr") if table is not None else soup.find_all("tr")
    streams_by_date: dict[datetime, TwitchTrackerStreamRow] = {}
    for row in row_els:
        cols = row.find_all("td")
        parsed = _parse_stream_row_cells(cols)
        if parsed is not None:
            streams_by_date[parsed.date] = parsed
    return sorted(streams_by_date.values(), key=lambda x: x.date)


def _game_hours_from_td(td: Any) -> float:
    span = td.find("span")
    raw = span.get_text(strip=True) if span else td.get_text(strip=True)
    return clean_float(raw)


def _parse_game_row_cells(cols: list[Any]) -> TwitchTrackerGameRow | None:
    if len(cols) != 7:
        return None

    game_name = cols[1].get_text(strip=True)
    if not game_name:
        return None

    return TwitchTrackerGameRow(
        name=game_name,
        rank=clean_int(cols[0].get_text(strip=True)),
        hours_streamed=_game_hours_from_td(cols[2]),
        avg_viewers=clean_int(cols[3].get_text(strip=True)),
        max_viewers=clean_int(cols[4].get_text(strip=True)),
        followers_per_hour=clean_float(cols[5].get_text(strip=True)),
        last_stream=parse_game_last_stream(cols[6].get_text(strip=True)),
    )


def collect_game_rows_from_games_html_file(path: Path) -> list[TwitchTrackerGameRow]:
    soup = _load_soup(Path(path))
    table = soup.find("table", id="games")
    if table is None:
        return []

    out: list[TwitchTrackerGameRow] = []
    for row in table.find_all("tr"):
        cols = row.find_all("td")
        parsed = _parse_game_row_cells(cols)
        if parsed is not None:
            out.append(parsed)
    return out


def collect_game_rows_from_pages_dir(*, pages_dir: Path) -> list[TwitchTrackerGameRow]:
    pages_dir = Path(pages_dir)
    out: list[TwitchTrackerGameRow] = []
    for file_name, path in iter_html_files(pages_dir):
        if not file_name.startswith("games_page"):
            continue
        out.extend(collect_game_rows_from_games_html_file(path))
    return out


def iter_html_files(pages_dir: Path) -> list[tuple[str, Path]]:
    pages_dir = Path(pages_dir)
    if not pages_dir.exists():
        return []
    return [
        (p.name, p)
        for p in sorted(pages_dir.iterdir(), key=lambda x: x.name)
        if p.is_file() and p.name.endswith(".html")
    ]


def _load_soup(path: Path) -> BeautifulSoup:
    return BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")


def parse_stream_pages(*, pages_dir: Path) -> list[TwitchTrackerStreamRow]:
    """
    Парсит HTML-страницы TwitchTracker и собирает информацию о стримах.

    Файлы без table#streams (например один <tr>) тоже обрабатываются.
    """
    streams_by_date: dict[datetime, TwitchTrackerStreamRow] = {}

    for file_name, path in iter_html_files(pages_dir):
        if file_name.startswith("games_page"):
            continue

        soup = _load_soup(path)
        for row in _iter_stream_rows_from_soup(soup):
            streams_by_date[row.date] = row

    return sorted(streams_by_date.values(), key=lambda x: x.date)


def parse_stream_file(*, path: Path) -> list[TwitchTrackerStreamRow]:
    """
    Parse a single TwitchTracker stream HTML file into normalized rows.

    Поддерживается полная страница с table id="streams" или фрагмент с одной/несколькими строками <tr>.
    Строки с одинаковой датой схлопываются (последняя побеждает).
    """
    soup = _load_soup(Path(path))
    return _iter_stream_rows_from_soup(soup)


def parse_game_pages(*, pages_dir: Path) -> list[TwitchTrackerGameRow]:
    """
    Парсит HTML-страницы с TwitchTracker и собирает информацию об играх.

    Несколько games_page*.html объединяются с правилом merge по имени игры
    (см. pipeline.transform.twitchtracker_transform.merge_twitchtracker_game_rows).
    """
    from pipeline.transform.twitchtracker_transform import merge_twitchtracker_game_rows

    raw = collect_game_rows_from_pages_dir(pages_dir=pages_dir)
    return merge_twitchtracker_game_rows(raw)


def parse_game_file(*, path: Path) -> list[TwitchTrackerGameRow]:
    """
    Parse a single TwitchTracker games HTML file into normalized rows.

    The file is expected to contain a table id="games".
    Дубликаты по имени игры в одном файле объединяются тем же правилом, что и между страницами.
    """
    from pipeline.transform.twitchtracker_transform import merge_twitchtracker_game_rows

    raw = collect_game_rows_from_games_html_file(Path(path))
    return merge_twitchtracker_game_rows(raw)


def load_streams_json(path: Path) -> list[TwitchTrackerStreamRow]:
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError(f"Expected list in streams.json: {path}")

    out: list[TwitchTrackerStreamRow] = []
    for item in rows:
        if not isinstance(item, dict):
            continue

        out.append(
            TwitchTrackerStreamRow(
                date=parse_stream_date(str(item.get("date") or "")),
                duration_hours=clean_duration_hours(item.get("duration")),
                avg_viewers=clean_int(item.get("avg_viewers")),
                max_viewers=clean_int(item.get("max_viewers")),
                followers=clean_int(item.get("followers")),
                views=clean_int(item.get("views")),
                title=str(item.get("title") or ""),
                games=[str(x) for x in (item.get("games") or []) if str(x).strip()],
            )
        )

    out.sort(key=lambda x: x.date)
    return out


def load_games_json(path: Path) -> list[TwitchTrackerGameRow]:
    rows = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(rows, list):
        raise ValueError(f"Expected list in games.json: {path}")

    out: list[TwitchTrackerGameRow] = []
    for item in rows:
        if not isinstance(item, dict):
            continue

        out.append(
            TwitchTrackerGameRow(
                name=str(item.get("game") or ""),
                rank=clean_int(item.get("rank")),
                hours_streamed=clean_float(item.get("hours_streamed")),
                avg_viewers=clean_int(item.get("avg_viewers")),
                max_viewers=clean_int(item.get("max_viewers")),
                followers_per_hour=clean_float(item.get("followers_per_hour")),
                last_stream=parse_game_last_stream(str(item.get("last_stream") or "")),
            )
        )

    out.sort(key=lambda x: (x.rank, x.name.casefold()))
    return out
