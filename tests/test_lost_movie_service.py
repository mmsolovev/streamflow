"""Тесты services.lost_movie_service: состояние Lost/фильмов без реального storage.

Запуск:
    .venv\\Scripts\\python.exe -m pytest tests/test_lost_movie_service.py -q

Все пути JSON-состояния подменяются на tmp_path.
"""
import json
import re

import pytest

import services.lost_movie_service as lms
from services.lost_movie_service import LostEpisodeRef

LOST_DATA = {
    "series": {
        "title_ru": "Остаться в живых",
        "title_en": "Lost",
        "seasons": [
            {
                "season_number": 1,
                "year": 2004,
                "episodes": [
                    {
                        "episode_number": 1,
                        "title_ru": "Пилот",
                        "title_en": "Pilot",
                        "imdb_rating": 8.5,
                    },
                    {
                        "episode_number": 2,
                        "title_ru": "Пилот 2",
                        "title_en": "Pilot 2",
                        "imdb_rating": 8.1,
                    },
                ],
            },
            {
                "season_number": 2,
                "year": 2005,
                "episodes": [
                    {
                        "episode_number": 1,
                        "title_ru": "Человек науки",
                        "title_en": "Man of Science",
                        "imdb_rating": 8.7,
                    },
                ],
            },
        ],
    }
}

HHMM_RE = re.compile(r"^\d{2}:\d{2}$")


@pytest.fixture(autouse=True)
def movie_storage(tmp_path, monkeypatch):
    """Перенаправляет все JSON-файлы состояния в tmp_path."""
    monkeypatch.setattr(lms, "LOST_DATA_PATH", tmp_path / "lost.json")
    monkeypatch.setattr(lms, "LOST_STATE_PATH", tmp_path / "lost_state.json")
    monkeypatch.setattr(lms, "MOVIE_STATE_PATH", tmp_path / "movie_state.json")
    return tmp_path


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _write_lost_data(data=LOST_DATA):
    _write(lms.LOST_DATA_PATH, data)


def _write_state(state):
    _write(lms.LOST_STATE_PATH, state)


# --- _normalize_hhmm ---


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("12:34", "12:34"),
        ("23:59", "23:59"),
        ("00:00", "00:00"),
        (" 12:34 ", "12:34"),
    ],
)
def test_normalize_hhmm_valid(raw, expected):
    assert lms._normalize_hhmm(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["24:00", "12:60", "ab:cd", "0:00", "1234", "12-34", "", None, 123],
)
def test_normalize_hhmm_invalid(raw):
    assert lms._normalize_hhmm(raw) is None


# --- загрузка/сохранение ---


def test_load_json_missing_file():
    assert lms.load_lost_data() == {}
    assert lms.load_lost_state() == {}


def test_load_json_non_dict_is_empty(movie_storage):
    _write(lms.LOST_DATA_PATH, ["not", "a", "dict"])
    assert lms.load_lost_data() == {}


def test_save_and_load_state_roundtrip():
    lms.save_lost_state({"season": 1, "episode": 2})
    assert lms.load_lost_state() == {"season": 1, "episode": 2}


# --- get_current_ref / статус ---


def test_current_ref_valid():
    _write_state({"season": 3, "episode": 7})
    assert lms.get_current_ref() == LostEpisodeRef(season=3, episode=7)


@pytest.mark.parametrize(
    "state",
    [
        {},
        {"season": "1", "episode": 2},
        {"season": 1, "episode": None},
        {"season": -1, "episode": 2},
    ],
)
def test_current_ref_invalid(state):
    _write_state(state)
    assert lms.get_current_ref() is None


def test_started_at_msk():
    _write_state({"started_at_msk": "21:05"})
    assert lms.get_started_at_msk() == "21:05"
    _write_state({})
    assert lms.get_started_at_msk() is None


def test_online_status_default_false():
    assert lms.get_online_status() is False
    _write_state({"online": True})
    assert lms.get_online_status() is True


# --- _find_episode / _next_ref ---


def test_find_episode_found():
    found = lms._find_episode(LOST_DATA, LostEpisodeRef(1, 2))
    assert found is not None
    _series, season, ep = found
    assert season["season_number"] == 1
    assert ep["title_ru"] == "Пилот 2"


def test_find_episode_missing():
    assert lms._find_episode(LOST_DATA, LostEpisodeRef(9, 9)) is None
    assert lms._find_episode({}, LostEpisodeRef(1, 1)) is None


def test_next_ref_within_season():
    assert lms._next_ref(LOST_DATA, LostEpisodeRef(1, 1)) == LostEpisodeRef(1, 2)


def test_next_ref_crosses_season():
    assert lms._next_ref(LOST_DATA, LostEpisodeRef(1, 2)) == LostEpisodeRef(2, 1)


def test_next_ref_end_of_series():
    assert lms._next_ref(LOST_DATA, LostEpisodeRef(2, 1)) is None


def test_next_ref_unknown_current():
    assert lms._next_ref(LOST_DATA, LostEpisodeRef(5, 5)) is None


# --- форматирование для чата ---


def test_format_current_offline_shows_last_watched():
    _write_state({"season": 1, "episode": 2, "online": False})
    message = lms.format_current_episode_for_chat()
    assert message == (
        "MrDestructoid Последняя просмотренная серия Lost: 1 сезон, 2 серия."
    )


def test_format_current_online_generic_series():
    _write_lost_data()
    _write_state({"season": 0, "episode": 0, "online": True})
    message = lms.format_current_episode_for_chat()
    assert message == "MrDestructoid Сериал: Остаться в живых (Lost)"


def test_format_current_online_full_episode():
    _write_lost_data()
    _write_state(
        {"season": 1, "episode": 1, "online": True, "started_at_msk": "20:00"}
    )
    message = lms.format_current_episode_for_chat()
    assert "Остаться в живых (Lost)" in message
    assert "1 сезон (2004)" in message
    assert "1 серия Пилот (Pilot)" in message
    assert "IMDB 8.5" in message
    assert "Начали серию ~20:00 МСК" in message


def test_format_current_online_without_started_time():
    _write_lost_data()
    _write_state({"season": 1, "episode": 1, "online": True})
    message = lms.format_current_episode_for_chat()
    assert "Начали серию" not in message


def test_format_current_online_no_state():
    _write_lost_data()
    assert lms.format_current_episode_for_chat() is None


def test_format_current_missing_titles_returns_none():
    data = {"series": {"title_ru": "", "title_en": "Lost", "seasons": []}}
    _write_lost_data(data)
    _write_state({"season": 0, "episode": 0, "online": True})
    assert lms.format_current_episode_for_chat() is None


def test_format_next_episode():
    _write_state({"season": 4, "episode": 8})
    assert lms.format_next_episode_for_chat() == (
        "MrDestructoid Последняя просмотренная серия Lost: 4 сезон, 8 серия."
    )
    _write_state({})
    assert lms.format_next_episode_for_chat() is None


# --- управление состоянием ---


def test_set_current_episode_marks_online_and_time():
    lms.set_current_episode(LostEpisodeRef(1, 2))
    state = lms.load_lost_state()
    assert state["season"] == 1
    assert state["episode"] == 2
    assert state["online"] is True
    assert HHMM_RE.match(state["started_at_msk"])


def test_set_current_episode_keeps_time_when_asked():
    _write_state({"started_at_msk": "19:30"})
    lms.set_current_episode(LostEpisodeRef(1, 2), set_started_time_now=False)
    assert lms.load_lost_state()["started_at_msk"] == "19:30"


def test_set_generic_series_state():
    lms.set_generic_series_state()
    state = lms.load_lost_state()
    assert (state["season"], state["episode"]) == (0, 0)
    assert state["online"] is True
    assert state["started_at_msk"] is None


def test_increment_episode_from_scratch_picks_first():
    _write_lost_data()
    assert lms.increment_episode() == LostEpisodeRef(1, 1)
    assert lms.get_current_ref() == LostEpisodeRef(1, 1)


def test_increment_episode_advances():
    _write_lost_data()
    _write_state({"season": 1, "episode": 1, "online": True})
    assert lms.increment_episode() == LostEpisodeRef(1, 2)


def test_increment_episode_at_series_end():
    _write_lost_data()
    _write_state({"season": 2, "episode": 1, "online": True})
    assert lms.increment_episode() is None


def test_increment_episode_without_data():
    assert lms.increment_episode() is None


def test_set_started_time_explicit():
    assert lms.set_started_time("21:05") is True
    assert lms.get_started_at_msk() == "21:05"


def test_set_started_time_now():
    assert lms.set_started_time(None) is True
    assert HHMM_RE.match(lms.get_started_at_msk())


def test_set_started_time_invalid_keeps_state():
    _write_state({"started_at_msk": "20:00"})
    assert lms.set_started_time("99:99") is False
    assert lms.get_started_at_msk() == "20:00"


def test_set_online_status_and_clear_all():
    lms.set_online_status(True)
    assert lms.get_online_status() is True
    lms.clear_all()
    assert lms.get_online_status() is False


def test_clear_time_only():
    _write_state({"season": 1, "episode": 1, "started_at_msk": "20:00"})
    lms.clear_time_only()
    state = lms.load_lost_state()
    assert state["started_at_msk"] is None
    assert state["season"] == 1


# --- фильм ---


def test_set_movie_returns_start_time():
    started = lms.set_movie("  Интерстеллар  ")
    assert HHMM_RE.match(started)
    state = json.loads(
        lms.MOVIE_STATE_PATH.read_text(encoding="utf-8")
    )
    assert state["name"] == "Интерстеллар"


def test_set_movie_empty_name():
    assert lms.set_movie("   ") is None
    assert not lms.MOVIE_STATE_PATH.exists()


def test_clear_movie_removes_file():
    lms.set_movie("Фильм")
    assert lms.MOVIE_STATE_PATH.exists()
    lms.clear_movie()
    assert not lms.MOVIE_STATE_PATH.exists()


def test_clear_movie_without_file_is_noop():
    lms.clear_movie()  # не должно падать


def test_set_movie_started_time_explicit():
    lms.set_movie("Фильм")
    assert lms.set_movie_started_time("22:10") == "22:10"


def test_set_movie_started_time_now():
    lms.set_movie("Фильм")
    assert HHMM_RE.match(lms.set_movie_started_time(None))


def test_set_movie_started_time_invalid():
    lms.set_movie("Фильм")
    assert lms.set_movie_started_time("25:00") is None


def test_clear_movie_time_keeps_name():
    lms.set_movie("Фильм")
    lms.clear_movie_time()
    state = json.loads(lms.MOVIE_STATE_PATH.read_text(encoding="utf-8"))
    assert state["name"] == "Фильм"
    assert state["started_at_msk"] is None


def test_format_movie_for_chat():
    assert lms.format_movie_for_chat() is None

    lms.set_movie("Интерстеллар")
    lms.set_movie_started_time("21:00")
    assert lms.format_movie_for_chat() == "Фильм Интерстеллар | Начали 21:00"

    lms.clear_movie_time()
    assert lms.format_movie_for_chat() == "Фильм Интерстеллар"
