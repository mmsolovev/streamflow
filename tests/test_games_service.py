"""Тесты services.games_service: поиск игры и форматирование !игры.

Запуск:
    .venv\\Scripts\\python.exe -m pytest tests/test_games_service.py -q

БД не используется: `_load_ranked_games` подменяется фейком.
"""
from datetime import datetime, timedelta

import pytest

import services.games_service as games_service
from services.games_service import (
    CandidateMatch,
    GameLookupResult,
    _build_candidate_match,
    _canonicalize_text,
    _clean_query,
    _extract_number_tokens,
    _format_date,
    _format_game_stats,
    _format_status,
    _format_suggestions,
    _is_confident_match,
    _normalize_text,
    build_game_response,
    build_games_help_message,
    find_game_lookup,
)


def _glr(name: str, **overrides) -> GameLookupResult:
    values = dict(
        name=name,
        streams_count=3,
        last_stream=datetime(2026, 10, 1, 18, 0),
        hours_streamed=12.5,
        rank=7,
        liked=None,
        completed=None,
    )
    values.update(overrides)
    return GameLookupResult(**values)


def _cm(name: str, score: float, ratio: float = 0.9, overlap: float = 0.9) -> CandidateMatch:
    return CandidateMatch(game=_glr(name), score=score, ratio=ratio, overlap=overlap)


@pytest.fixture(autouse=True)
def _fixed_env(monkeypatch):
    monkeypatch.setattr(games_service, "GAMES_SHEET_URL", "https://sheet.example")
    # Фиксированный сдвиг UTC→локаль, как Europe/Moscow.
    monkeypatch.setattr(
        games_service,
        "utc_to_tracker",
        lambda value: value + timedelta(hours=3) if value else None,
    )


def _stub_games(monkeypatch, games):
    async def _fake():
        return games

    monkeypatch.setattr(games_service, "_load_ranked_games", _fake)


# --- нормализация ---


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Hades  ", "Hades"),
        ("Hades II", "Hades II"),
        (None, ""),
        ("", ""),
        ("!!!", ""),
        ("\x00bad", "bad"),
    ],
)
def test_clean_query(raw, expected):
    assert _clean_query(raw) == expected


def test_normalize_text():
    assert _normalize_text("  Hades   II ") == "hades ii"


def test_canonicalize_text_roman_and_punctuation():
    assert _canonicalize_text("Dark Souls III") == "dark souls 3"
    assert _canonicalize_text("The Witcher!") == "the witcher"


def test_extract_number_tokens():
    # Римские числа нормализуются, слова-числительные — нет (в отличие от
    # hltb_service._canonicalize): «Two» остаётся текстом.
    assert _extract_number_tokens("Unravel Two") == set()
    assert _extract_number_tokens("Dark Souls III") == {"3"}
    assert _extract_number_tokens("Hades 2") == {"2"}
    assert _extract_number_tokens("Hades") == set()


# --- форматирование ---


def test_format_date_none():
    assert _format_date(None) == "н/д"


def test_format_date_converts_to_local():
    # 21:00 UTC 1 октября → 00:00 2 октября в локали (+3).
    assert _format_date(datetime(2026, 10, 1, 21, 0)) == "02.10.2026"


@pytest.mark.parametrize(
    ("liked", "completed", "expected"),
    [
        (True, True, "Игра пройдена и очень понравилась"),
        (False, True, "Игра пройдена"),
        (True, False, "Игра очень понравилась"),
        (None, None, None),
        (False, False, None),
    ],
)
def test_format_status(liked, completed, expected):
    assert _format_status(liked, completed) == expected


def test_doc_suffix():
    assert games_service._doc_suffix() == " | Все игры канала https://sheet.example"
    games_service.GAMES_SHEET_URL = ""
    try:
        assert games_service._doc_suffix() == " Список игр: ссылка не настроена"
    finally:
        games_service.GAMES_SHEET_URL = "https://sheet.example"


def test_format_game_stats_full():
    message = _format_game_stats(_glr("Hades", liked=True, completed=True))
    assert "Игра: Hades" in message
    assert "Было стримов по игре: 3" in message
    assert "Последний стрим: 01.10.2026" in message
    assert "Времени в игре: 12 ч 30 м (#7)" in message
    assert "Игра пройдена и очень понравилась" in message


def test_format_game_stats_without_status():
    message = _format_game_stats(_glr("Hades"))
    assert "пройдена" not in message


def test_format_suggestions_limits_visible():
    matches = [_cm(f"Game{i}", 0.9) for i in range(5)]
    message = _format_suggestions(matches)
    assert "«Game0»" in message
    assert "«Game2»" in message
    assert "«Game3»" not in message
    assert "и еще 2" in message


def test_format_suggestions_no_hidden():
    assert _format_suggestions([_cm("A", 0.9)]) == "«A»"


# --- матчинг ---


def test_find_exact_match_ignores_case_and_roman():
    games = [_glr("Dark Souls III")]
    assert games_service._find_exact_match("dark souls 3", games).name == (
        "Dark Souls III"
    )


def test_find_exact_match_missing():
    assert games_service._find_exact_match("zelda", [_glr("Hades")]) is None
    assert games_service._find_exact_match("", [_glr("Hades")]) is None


def test_candidate_number_mismatch_rejected():
    # «Hades II» (2) не должен матчить «Hades III» (3).
    assert _build_candidate_match("Hades II", _glr("Hades III")) is None


def test_candidate_word_number_is_not_rejected():
    # Особенность текущего матчера: слова-числительные не нормализуются,
    # поэтому «Unravel Two» формально похож на «Unravel» (номер не сверяется).
    match = _build_candidate_match("Unravel Two", _glr("Unravel"))
    assert match is not None


def test_candidate_number_match_accepted():
    match = _build_candidate_match("unravel 2", _glr("Unravel II"))
    assert match is not None


def test_candidate_far_below_threshold():
    assert _build_candidate_match("zzzzz", _glr("Hades")) is None


def test_similar_matches_sorted_by_score():
    games = [_glr("Hades"), _glr("Hellblade")]
    matches = games_service._find_similar_matches("hades", games)
    assert matches[0].game.name == "Hades"


def test_is_confident_low_score():
    assert not _is_confident_match("hades", _cm("Hades", 0.5), [])


def test_is_confident_high_score_no_others():
    assert _is_confident_match("hades", _cm("Hades", 0.95), [])


def test_is_confident_small_gap_low_ratio():
    best = _cm("Hades", 0.9, ratio=0.90)
    other = _cm("Hades II", 0.85)
    assert not _is_confident_match("hades", best, [other])


def test_is_confident_small_gap_high_ratio():
    best = _cm("Hades", 0.9, ratio=0.98)
    other = _cm("Hades II", 0.85)
    assert _is_confident_match("hades", best, [other])


def test_is_confident_number_match_wins():
    best = _cm("Unravel II", 0.9, ratio=0.5)
    other = _cm("Unravel", 0.89)
    assert _is_confident_match("unravel 2", best, [other])


# --- find_game_lookup ---


async def test_lookup_empty_query(monkeypatch):
    _stub_games(monkeypatch, [_glr("Hades")])
    assert await find_game_lookup("  ") is None


async def test_lookup_exact(monkeypatch):
    _stub_games(monkeypatch, [_glr("Hades")])
    result = await find_game_lookup("hades")
    assert result.name == "Hades"


async def test_lookup_confident_similar(monkeypatch):
    # Проводка find_game_lookup: точного совпадения нет, но лучший
    # кандидат признан уверенным — возвращается его игра.
    games = [_glr("Hades"), _glr("Hades II")]
    _stub_games(monkeypatch, games)
    monkeypatch.setattr(games_service, "_find_exact_match", lambda q, g: None)
    monkeypatch.setattr(games_service, "_is_confident_match", lambda *args: True)

    result = await find_game_lookup("hades")
    assert result is not None and result.name == "Hades"


async def test_lookup_ambiguous_returns_none(monkeypatch):
    # Есть похожие варианты, но ни один не уверенный — lookup молчит.
    games = [_glr("Hades"), _glr("Hades II")]
    _stub_games(monkeypatch, games)
    monkeypatch.setattr(games_service, "_find_exact_match", lambda q, g: None)
    monkeypatch.setattr(games_service, "_is_confident_match", lambda *args: False)

    assert await find_game_lookup("hades") is None


async def test_lookup_nothing_found(monkeypatch):
    _stub_games(monkeypatch, [_glr("Hades")])
    assert await find_game_lookup("квантовая физика") is None


# --- build_game_response ---


async def test_response_empty_query_returns_help(monkeypatch):
    _stub_games(monkeypatch, [])
    assert await build_game_response("") == build_games_help_message()


async def test_response_exact_match(monkeypatch):
    _stub_games(monkeypatch, [_glr("Hades")])
    message = await build_game_response("hades")
    assert message.startswith("Игра: Hades")
    assert message.endswith("https://sheet.example")


async def test_response_no_matches_at_all(monkeypatch):
    _stub_games(monkeypatch, [_glr("Hades")])
    message = await build_game_response("квантовая физика")
    assert "не найдена, и похожих вариантов тоже нет" in message


async def test_response_confident_similar_with_alternatives(monkeypatch):
    games = [_glr("Hades"), _glr("Hades II")]
    _stub_games(monkeypatch, games)
    monkeypatch.setattr(games_service, "_find_exact_match", lambda q, g: None)
    monkeypatch.setattr(games_service, "_is_confident_match", lambda *args: True)

    message = await build_game_response("hades")
    assert "скорее всего это «Hades»" in message
    assert "другие похожие результаты: 1" in message
    assert "«Hades II»" in message


async def test_response_ambiguous_offers_suggestions(monkeypatch):
    games = [_glr("Hades"), _glr("Hades II")]
    _stub_games(monkeypatch, games)
    monkeypatch.setattr(games_service, "_find_exact_match", lambda q, g: None)
    monkeypatch.setattr(games_service, "_is_confident_match", lambda *args: False)
    message = await build_game_response("hades")
    assert "Возможно, имелось в виду" in message
    assert "«Hades»" in message
