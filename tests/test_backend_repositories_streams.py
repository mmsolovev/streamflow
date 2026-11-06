"""Tests for stream repository VOD aggregation."""
import unittest

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


class StreamVodMapTests(unittest.IsolatedAsyncioTestCase):
    async def test_collects_all_unique_urls_per_stream(self):
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

        self.assertEqual(
            mapping[1],
            [
                "https://www.twitch.tv/videos/1",
                "https://www.twitch.tv/videos/2",
            ],
        )
        self.assertEqual(mapping[2], ["https://www.twitch.tv/videos/3"])

    async def test_empty_stream_ids_returns_empty_mapping(self):
        self.assertEqual(await _vods_map(_FakeSession([]), []), {})


if __name__ == "__main__":
    unittest.main()
