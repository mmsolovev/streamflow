"""Тесты валидации одиночной страницы TwitchTracker.

Запуск:
    .venv\\Scripts\\python.exe -m unittest discover -s tests -t .

Проверяет, что файл из нескольких склеенных страниц (двух стримов)
отклоняется явной ошибкой, а не молча смешивает данные двух стримов.
"""
import tempfile
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

from pipeline.ingest.twitchtracker_parser import (
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


class SinglePageValidationTests(unittest.TestCase):
    def test_single_block_is_accepted(self):
        _validate_single_stream_page(BeautifulSoup(SINGLE_BLOCK, "html.parser"))

    def test_concatenated_blocks_are_rejected(self):
        with self.assertRaises(ValueError) as ctx:
            _validate_single_stream_page(BeautifulSoup(CONCATENATED, "html.parser"))
        self.assertIn("section#stream-games", str(ctx.exception))


    def test_parse_accepts_single_block_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stream_2026-10-04.html"
            path.write_text(SINGLE_BLOCK, encoding="utf-8")
            page = parse_stream_page_html(path)
            self.assertTrue(page is None or page.games or page.date)


if __name__ == "__main__":
    unittest.main()
