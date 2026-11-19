"""Tests for stream repository VOD aggregation."""

from backend.repositories.streams import _vods_map


class _FakeResult:
    def __init__(self, rows: list[tuple[int, str | None]]) -> None:
        self._rows = rows

    def all(self) -> list[tuple[int, str | None]]:
        return self._rows


class _FakeSession:
    def __init__(self, rows: list[tuple[int, str | None]]) -> None:
        self._rows = rows

    async def execute(self, _statement) -> _FakeResult:
        return _FakeResult(self._rows)


async def test_collects_all_unique_urls_per_stream():
    session = _FakeSession(
        [
            (1, "https://www.twitch.tv/videos/1"),
            (1, "https://www.twitch.tv/videos/2"),
            (1, "https://www.twitch.tv/videos/1"),
            (1, None),
            (2, "https://www.twitch.tv/videos/3"),
        ]
    )

    mapping = await _vods_map(session, [1, 2])

    assert mapping[1] == [
        "https://www.twitch.tv/videos/1",
        "https://www.twitch.tv/videos/2",
    ]
    assert mapping[2] == ["https://www.twitch.tv/videos/3"]


async def test_empty_stream_ids_returns_empty_mapping():
    assert await _vods_map(_FakeSession([]), []) == {}
