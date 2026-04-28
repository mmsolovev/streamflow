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
    if s.endswith("hrs"):
        s = s[: -3]
    return float(s)


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

    """
    streams_by_date: dict[datetime, TwitchTrackerStreamRow] = {}

    for file_name, path in iter_html_files(pages_dir):
        if file_name.startswith("games_page"):
            continue

        soup = _load_soup(path)
        table = soup.find("table", id="streams")
        if table is None:
            continue

        for row in table.find_all("tr"):
            cols = row.find_all("td")
            if len(cols) != 8:
                continue

            date = parse_stream_date(cols[0].get_text(strip=True))
            games: list[str] = []

            for img in cols[7].find_all("img"):
                game_name = img.get("data-original-title")
                if game_name:
                    games.append(game_name)

            streams_by_date[date] = TwitchTrackerStreamRow(
                date=date,
                duration_hours=clean_duration_hours(cols[1].get_text(strip=True)),
                avg_viewers=clean_int(cols[2].get_text(strip=True)),
                max_viewers=clean_int(cols[3].get_text(strip=True)),
                followers=clean_int(cols[4].get_text(strip=True)),
                views=clean_int(cols[5].get_text(strip=True)),
                title=cols[6].get_text(strip=True),
                games=games,
            )

    return sorted(streams_by_date.values(), key=lambda x: x.date)


def parse_stream_file(*, path: Path) -> list[TwitchTrackerStreamRow]:
    """
    Parse a single TwitchTracker stream HTML file into normalized rows.

    The file may contain multiple rows (table id="streams"). Returned rows are de-duplicated by date.
    """
    soup = _load_soup(Path(path))
    table = soup.find("table", id="streams")
    if table is None:
        return []

    streams_by_date: dict[datetime, TwitchTrackerStreamRow] = {}
    for row in table.find_all("tr"):
        cols = row.find_all("td")
        if len(cols) != 8:
            continue

        date = parse_stream_date(cols[0].get_text(strip=True))
        games: list[str] = []
        for img in cols[7].find_all("img"):
            game_name = img.get("data-original-title")
            if game_name:
                games.append(game_name)

        streams_by_date[date] = TwitchTrackerStreamRow(
            date=date,
            duration_hours=clean_duration_hours(cols[1].get_text(strip=True)),
            avg_viewers=clean_int(cols[2].get_text(strip=True)),
            max_viewers=clean_int(cols[3].get_text(strip=True)),
            followers=clean_int(cols[4].get_text(strip=True)),
            views=clean_int(cols[5].get_text(strip=True)),
            title=cols[6].get_text(strip=True),
            games=games,
        )

    return sorted(streams_by_date.values(), key=lambda x: x.date)


def parse_game_pages(*, pages_dir: Path) -> list[TwitchTrackerGameRow]:
    """
    Парсит HTML-страницы с TwitchTracker и собирает информацию об играх.

    """
    games_by_name: dict[str, TwitchTrackerGameRow] = {}

    for file_name, path in iter_html_files(pages_dir):
        if not file_name.startswith("games_page"):
            continue

        soup = _load_soup(path)
        table = soup.find("table", id="games")
        if table is None:
            continue

        for row in table.find_all("tr"):
            cols = row.find_all("td")
            if len(cols) != 7:
                continue

            game_name = cols[1].get_text(strip=True)
            games_by_name[game_name] = TwitchTrackerGameRow(
                name=game_name,
                rank=clean_int(cols[0].get_text(strip=True)),
                hours_streamed=clean_float(cols[2].get_text(strip=True)),
                avg_viewers=clean_int(cols[3].get_text(strip=True)),
                max_viewers=clean_int(cols[4].get_text(strip=True)),
                followers_per_hour=clean_float(cols[5].get_text(strip=True)),
                last_stream=parse_game_last_stream(cols[6].get_text(strip=True)),
            )

    return sorted(games_by_name.values(), key=lambda x: (x.rank, x.name.casefold()))


def parse_game_file(*, path: Path) -> list[TwitchTrackerGameRow]:
    """
    Parse a single TwitchTracker games HTML file into normalized rows.

    The file is expected to contain a table id="games".
    Returned rows are de-duplicated by game name.
    """
    soup = _load_soup(Path(path))
    table = soup.find("table", id="games")
    if table is None:
        return []

    games_by_name: dict[str, TwitchTrackerGameRow] = {}
    for row in table.find_all("tr"):
        cols = row.find_all("td")
        if len(cols) != 7:
            continue

        game_name = cols[1].get_text(strip=True)
        games_by_name[game_name] = TwitchTrackerGameRow(
            name=game_name,
            rank=clean_int(cols[0].get_text(strip=True)),
            hours_streamed=clean_float(cols[2].get_text(strip=True)),
            avg_viewers=clean_int(cols[3].get_text(strip=True)),
            max_viewers=clean_int(cols[4].get_text(strip=True)),
            followers_per_hour=clean_float(cols[5].get_text(strip=True)),
            last_stream=parse_game_last_stream(cols[6].get_text(strip=True)),
        )

    return sorted(games_by_name.values(), key=lambda x: (x.rank, x.name.casefold()))


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
