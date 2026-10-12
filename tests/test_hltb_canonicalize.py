"""Тесты канонизации названий в services.hltb_service.

Запуск:
    .venv\\Scripts\\python.exe -m unittest discover -s tests -t .
"""
import unittest

from services.hltb_service import _canonicalize


class CanonicalizeTests(unittest.TestCase):
    def test_number_words_match_digits(self):
        self.assertEqual(_canonicalize("UNRAVEL 2"), _canonicalize("Unravel Two"))

    def test_number_words_to_digits(self):
        self.assertEqual(_canonicalize("It Takes Two"), "it takes 2")
        self.assertEqual(_canonicalize("unravel two"), "unravel 2")

    def test_roman_numerals(self):
        self.assertEqual(_canonicalize("Dark Souls III"), "dark souls 3")
        self.assertEqual(_canonicalize("DOOM II"), "doom 2")

    def test_punctuation_and_case(self):
        self.assertEqual(_canonicalize("  Gears of War!  "), "gears of war")

    def test_empty_values(self):
        self.assertEqual(_canonicalize(None), "")
        self.assertEqual(_canonicalize(""), "")


if __name__ == "__main__":
    unittest.main()
