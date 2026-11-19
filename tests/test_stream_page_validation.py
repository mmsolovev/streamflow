"""Тесты валидации одиночной страницы TwitchTracker.

Запуск:
    .venv\\Scripts\\python.exe -m pytest tests/test_stream_page_validation.py -q

Проверяет, что файл из нескольких склеенных страниц (двух стримов)
отклоняется явной ошибкой, а не молча смешивает данные двух стримов.
"""
import pytest
from datetime import datetime
from bs4 import BeautifulSoup

from pipeline.ingest.twitchtracker_parser import (
    _parse_stream_timestamp,
    _validate_single_stream_page,
    parse_stream_page_html,
)

SINGLE_BLOCK = """
<html><body>
<div id="main-col">
  <div class="stream-timestamps"></div>
  <span data-date-format="d/M/Y H:i">04/Oct/2026 18:00</span>
  <section id="stream-games">
    <div class="g-x-wrapper">
      <a class="g-x-s-title" href="/tabula/games/506445">End of Abyss</a>
    </div>
  </section>
</div>
</body></html>
"""

CONCATENATED = SINGLE_BLOCK + SINGLE_BLOCK


def test_single_block_is_accepted():
    _validate_single_stream_page(BeautifulSoup(SINGLE_BLOCK, "html.parser"))


def test_concatenated_blocks_are_rejected():
    with pytest.raises(ValueError) as exc_info:
        _validate_single_stream_page(BeautifulSoup(CONCATENATED, "html.parser"))
    assert "section#stream-games" in str(exc_info.value)


def test_parse_accepts_single_block_file(tmp_path):
    path = tmp_path / "stream_2026-10-04.html"
    path.write_text(SINGLE_BLOCK, encoding="utf-8")
    page = parse_stream_page_html(path)
    assert page is None or page.games or page.date


def test_stream_timestamp_uses_historical_page_year():
    value = _parse_stream_timestamp(
        "Tue, Jan 24, 22:05",
        reference_date=datetime(2023, 1, 24),
    )
    assert value == datetime(2023, 1, 24, 19, 5)


def test_stream_timestamp_handles_new_year_boundary():
    value = _parse_stream_timestamp(
        "Sun, Jan 1, 00:15",
        reference_date=datetime(2022, 12, 31),
    )
    assert value == datetime(2022, 12, 31, 21, 15)
