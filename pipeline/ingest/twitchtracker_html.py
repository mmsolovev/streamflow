from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

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


def _parse_date(value: str) -> datetime:
    return datetime.strptime(value, "%d/%b/%Y %H:%M")


def _parse_last_stream(value: str) -> datetime:
    return datetime.strptime(value, "%d/%b/%Y")


def _parse_int(value: str) -> int:
    return int(str(value).replace(",", "").strip())


def _parse_float(value: str) -> float:
    return float(str(value).replace(",", "").strip())


def _parse_duration_hours(value: str) -> float:
    normalized = str(value).replace(" ", "").replace(" hrs", "hrs").replace("hrs", "")
    return float(normalized)


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
    Parses all non-games TwitchTracker HTML pages into unique stream rows.

    Dedup key: `date` (last one wins).
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

            date = _parse_date(cols[0].get_text(strip=True))
            games: list[str] = []

            for img in cols[7].find_all("img"):
                game_name = img.get("data-original-title")
                if game_name:
                    games.append(game_name)

            streams_by_date[date] = TwitchTrackerStreamRow(
                date=date,
                duration_hours=_parse_duration_hours(cols[1].get_text(strip=True)),
                avg_viewers=_parse_int(cols[2].get_text(strip=True)),
                max_viewers=_parse_int(cols[3].get_text(strip=True)),
                followers=_parse_int(cols[4].get_text(strip=True)),
                views=_parse_int(cols[5].get_text(strip=True)),
                title=cols[6].get_text(strip=True),
                games=games,
            )

    return sorted(streams_by_date.values(), key=lambda x: x.date)


def parse_game_pages(*, pages_dir: Path) -> list[TwitchTrackerGameRow]:
    """
    Parses all games TwitchTracker HTML pages into unique game rows.

    Dedup key: `name` (last one wins).
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
                rank=_parse_int(cols[0].get_text(strip=True)),
                hours_streamed=_parse_float(cols[2].get_text(strip=True)),
                avg_viewers=_parse_int(cols[3].get_text(strip=True)),
                max_viewers=_parse_int(cols[4].get_text(strip=True)),
                followers_per_hour=_parse_float(cols[5].get_text(strip=True)),
                last_stream=_parse_last_stream(cols[6].get_text(strip=True)),
            )

    return sorted(games_by_name.values(), key=lambda x: (x.rank, x.name.casefold()))
