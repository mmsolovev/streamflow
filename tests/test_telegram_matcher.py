"""Тесты чистых функций telegram.matcher.

Запуск:
    .venv\\Scripts\\python.exe -m pytest tests/test_telegram_matcher.py -q

aiogram, БД и сеть не требуются: matcher ничего из этого не импортирует.
"""
from datetime import datetime, timedelta, timezone

import pytest

from telegram.templates import build_finished_entities, build_finished_text
from telegram.matcher import (
    build_channel_link_matcher,
    extract_urls,
    has_channel_link,
    in_rebind_window,
    in_window,
    is_already_finished,
    normalize_dt,
    normalize_text,
    pick_candidate,
    post_text,
)


CHANNEL_URL = "https://twitch.tv/tabula"


def matcher():
    return build_channel_link_matcher(CHANNEL_URL)


def test_none_for_bad_url():
    assert build_channel_link_matcher(None) is None
    assert build_channel_link_matcher("") is None
    assert build_channel_link_matcher("twitch.tv") is None
    assert build_channel_link_matcher("https://twitch.tv/") is None


@pytest.mark.parametrize(
    "text",
    [
        "Стрим онлайн https://twitch.tv/tabula",
        "https://twitch.tv/tabula",
        "https://www.twitch.tv/tabula",
        "https://m.twitch.tv/tabula",
        "twitch.tv/tabula",
        "www.twitch.tv/tabula",
        "Сегодня стрим! twitch.tv/tabula играем в игру",
        "https://twitch.tv/tabula/",
        "https://twitch.tv/Tabula",
        # Ссылка слит с текстом и без пробела, плюс пунктуация в конце.
        "Стрим онлайн!https://twitch.tv/tabula",
        "Стрим онлайн twitch.tv/tabula,",
        'Стрим онлайн (<a href="https://twitch.tv/tabula">канал</a>)',
    ],
)
def test_announcement_shapes(text):
    assert has_channel_link(text, matcher())


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "Стрим онлайн",
        "Просто новость про обновление",
        "Реклама магазина",
        "https://twitch.tv/videos/123456789",
        "https://twitch.tv/tabula_news",
        "https://twitch.tv/tabula2",
        "https://twitch.tv/otherchannel",
        "https://tracker.example.com/twitch.tv/tabula",
        "https://example.com/?ref=twitch.tv/tabula",
    ],
)
def test_non_announcements(text):
    assert not has_channel_link(text, matcher())


def test_none_matcher_never_matches():
    assert not has_channel_link("Стрим онлайн https://twitch.tv/tabula", None)


def test_explicit_domains():
    m = build_channel_link_matcher(CHANNEL_URL, ["twitch.tv", "twitch.tv"])
    assert has_channel_link("https://twitch.tv/tabula", m)


@pytest.mark.parametrize(
    "text",
    [
        "Стрим окончен. Запись https://twitch.tv/videos/1",
        "Стрим окончен.",
        "Окончилась трансляция",
        "строка со ссылкой www.twitch.tv/videos/999",
    ],
)
def test_finished_texts(text):
    assert is_already_finished(text)


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "Стрим онлайн https://twitch.tv/tabula",
        "Стрим онлайн, запись будет завтра",
        "Начинаем стрим!",
    ],
)
def test_announcement_texts(text):
    assert not is_already_finished(text)


def test_bot_format_is_finished():
    # Регрессия: в подписи бота больше нет ни URL, ни слова «оконч» —
    # только заголовок «Запись стрима» и подпись ссылки. Без этого
    # маркера готовый пост выглядел бы как свежий анонс и привязался бы
    # к следующему стриму повторно.
    assert is_already_finished(build_finished_text(["https://twitch.tv/videos/1"]))
    text, _entities = build_finished_entities(["https://twitch.tv/videos/1"])
    assert is_already_finished(text)


def test_streamer_manual_format_is_finished():
    # Тот же заголовок пишет стример от руки — такой пост тоже готовый.
    assert is_already_finished("Запись стрима:\n\n🎥TWITCH~")


def test_phrase_about_future_recording_is_not_finished():
    # «Запись» в анонсе — обычный текст, его нельзя считать меткой.
    assert not is_already_finished("Запись стрима будет через час")


def test_normalize_text():
    assert normalize_text("  Стрим   ОНЛАЙН\n") == "стрим онлайн"
    assert normalize_text(None) == ""


def test_extract_urls():
    urls = extract_urls("a https://twitch.tv/tabula b twitch.tv/x")
    assert urls == ["https://twitch.tv/tabula"]
    assert extract_urls("nothing here") == []


def test_post_text_joins_caption_and_text():
    post = {"caption_snapshot": "подпись", "text_snapshot": None}
    assert post_text(post) == "подпись"
    post = {"caption_snapshot": "подпись", "text_snapshot": "текст"}
    assert post_text(post) == "подпись\nтекст"
    assert post_text({}) == ""


def test_normalize_dt_variants():
    aware = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
    assert normalize_dt(aware) == datetime(2026, 10, 1, 12, 0)
    assert normalize_dt("2026-10-01T12:00:00Z") == datetime(2026, 10, 1, 12, 0)
    assert normalize_dt("2026-10-01T15:00:00+03:00") == datetime(2026, 10, 1, 12, 0)
    naive = datetime(2026, 10, 1, 12, 0)
    assert normalize_dt(naive) == naive
    assert normalize_dt(None) is None
    assert normalize_dt("") is None
    assert normalize_dt("не дата") is None


WINDOW_START = datetime(2026, 10, 1, 20, 0)
WINDOW_END = datetime(2026, 10, 1, 22, 0)


def test_inside():
    assert in_window(WINDOW_START - timedelta(minutes=5), started_at=WINDOW_START)
    assert in_window(WINDOW_START, started_at=WINDOW_START, ended_at=WINDOW_END)
    assert in_window(
        WINDOW_START + timedelta(minutes=30), started_at=WINDOW_START, ended_at=WINDOW_END
    )


def test_outside():
    assert not in_window(
        WINDOW_START - timedelta(hours=1, minutes=1), started_at=WINDOW_START, ended_at=WINDOW_END
    )
    assert not in_window(
        WINDOW_START + timedelta(minutes=61), started_at=WINDOW_START, ended_at=WINDOW_END
    )


def test_boundaries_inclusive():
    assert in_window(
        WINDOW_START - timedelta(hours=1), started_at=WINDOW_START, ended_at=WINDOW_END
    )
    assert in_window(
        WINDOW_START + timedelta(minutes=60), started_at=WINDOW_START, ended_at=WINDOW_END
    )


def test_custom_window():
    posted = WINDOW_START - timedelta(minutes=10)
    assert in_window(posted, started_at=WINDOW_START, before_hours=0.2)
    assert not in_window(posted, started_at=WINDOW_START, before_hours=0.1)


def test_window_missing_values():
    assert not in_window(None, started_at=WINDOW_START)
    assert not in_window(WINDOW_START, started_at=None)


def test_end_time_does_not_expand_announcement_window():
    assert not in_window(
        WINDOW_START + timedelta(hours=2),
        started_at=WINDOW_START,
        ended_at=WINDOW_START + timedelta(hours=5),
    )


REBIND_NEW_START = datetime(2026, 10, 1, 21, 5)


def test_recent_previous_stream():
    previous_end = REBIND_NEW_START - timedelta(minutes=10)
    assert in_rebind_window(previous_end, REBIND_NEW_START, window_minutes=180)


def test_old_previous_stream():
    previous_end = REBIND_NEW_START - timedelta(hours=5)
    assert not in_rebind_window(previous_end, REBIND_NEW_START, window_minutes=180)


def test_rebind_missing_values():
    assert not in_rebind_window(None, REBIND_NEW_START)
    assert not in_rebind_window(REBIND_NEW_START, None)


HIDDEN_CAPTION = (
    "⏺Стрим онлайн! Заканчиваем Алана, попытка номер 2 😎\n\n💬TWITCH~"
)
HIDDEN_CHANNEL = ["https://twitch.tv/tabula"]


def test_text_alone_has_no_link():
    """Регрессия: ссылка на канал скрыта подписью, в тексте её нет.

    Стример пишет «💬TWITCH~» — адрес лежит в сущности text_link. Разбор
    одного текста такой пост отбрасывал как новость, и стрим терялся: в
    логах было `No Telegram announcement found`.
    """
    # Предположение, на котором стоит вся починка: в тексте адреса нет.
    assert not has_channel_link(HIDDEN_CAPTION, matcher())
    assert "twitch.tv" not in HIDDEN_CAPTION


def test_hidden_link_is_found_in_entities():
    assert has_channel_link(HIDDEN_CAPTION, matcher(), HIDDEN_CHANNEL)


def test_hidden_link_survives_pick_candidate():
    started = datetime(2026, 10, 2, 16, 0)
    post = {
        "message_id": 4663,
        "posted_at": started - timedelta(minutes=5),
        "caption_snapshot": HIDDEN_CAPTION,
        "text_snapshot": None,
        "is_forward": False,
        "link_urls": HIDDEN_CHANNEL,
    }
    chosen = pick_candidate(
        [post],
        matcher=matcher(),
        started_at=started,
        ended_at=started + timedelta(hours=5),
    )
    assert chosen is not None, "анонс со скрытой ссылкой должен выбираться"
    assert chosen["message_id"] == 4663


def test_post_without_entities_still_skipped():
    # Ссылок не было и в тексте нет: обычная новость остаётся новостью.
    post = {
        "message_id": 1,
        "posted_at": datetime(2026, 10, 2, 15, 55),
        "caption_snapshot": HIDDEN_CAPTION,
        "text_snapshot": None,
        "is_forward": False,
    }
    chosen = pick_candidate(
        [post],
        matcher=matcher(),
        started_at=datetime(2026, 10, 2, 16, 0),
        ended_at=datetime(2026, 10, 2, 21, 0),
    )
    assert chosen is None


def test_finished_marker_hidden_in_entity():
    # Стример дописал запись скрытой ссылкой на /videos/ — пост готов,
    # переписывать его заново нельзя.
    assert not is_already_finished(HIDDEN_CAPTION)
    assert is_already_finished(
        HIDDEN_CAPTION, ["https://www.twitch.tv/videos/2889608958"]
    )


def test_hidden_finished_post_not_picked():
    post = {
        "message_id": 4663,
        "posted_at": datetime(2026, 10, 2, 15, 55),
        "caption_snapshot": HIDDEN_CAPTION,
        "text_snapshot": None,
        "is_forward": False,
        "link_urls": ["https://www.twitch.tv/videos/2889608958"],
    }
    chosen = pick_candidate(
        [post],
        matcher=matcher(),
        started_at=datetime(2026, 10, 2, 16, 0),
        ended_at=datetime(2026, 10, 2, 21, 0),
    )
    assert chosen is None


PICK_START = datetime(2026, 10, 1, 20, 0)
PICK_END = datetime(2026, 10, 1, 22, 0)


def _post(
    message_id,
    posted_at,
    caption="Стрим онлайн https://twitch.tv/tabula",
    **extra,
):
    row = {
        "message_id": message_id,
        "posted_at": posted_at,
        "caption_snapshot": caption,
        "text_snapshot": None,
        "is_forward": False,
    }
    row.update(extra)
    return row


def _pick(posts, **extra):
    kwargs = {
        "matcher": matcher(),
        "started_at": PICK_START,
        "ended_at": PICK_END,
        "before_hours": 1,
        "after_minutes": 60,
    }
    kwargs.update(extra)
    return pick_candidate(posts, **kwargs)


def _pick_id(posts, **extra):
    """message_id выбранного поста; падение тут читаемее, чем в assert None."""
    chosen = _pick(posts, **extra)
    if chosen is None:
        pytest.fail("ожидался кандидат, но вернулся None")
    return chosen["message_id"]


def test_picks_announcement_closest_to_stream_start():
    posts = [
        _post(1, PICK_START - timedelta(minutes=5)),
        _post(2, PICK_START + timedelta(minutes=2)),
        _post(3, PICK_START - timedelta(minutes=10)),
    ]
    assert _pick_id(posts) == 2


def test_candidate_window_is_one_hour_before_and_after_start():
    posts = [
        _post(1, PICK_START - timedelta(hours=1, seconds=1)),
        _post(2, PICK_START + timedelta(minutes=59)),
        _post(3, PICK_START + timedelta(hours=1, seconds=1)),
    ]
    assert _pick_id(posts) == 2


def test_pick_empty():
    assert _pick([]) is None


def test_skips_forwards():
    posts = [
        _post(1, PICK_START - timedelta(minutes=5), is_forward=True),
        _post(2, PICK_START - timedelta(minutes=20)),
    ]
    assert _pick_id(posts) == 2


def test_skips_posts_without_channel_link():
    posts = [
        _post(1, PICK_START - timedelta(minutes=1), caption="Реклама магазина"),
        _post(
            2,
            PICK_START - timedelta(minutes=5),
            caption="Стрим онлайн https://twitch.tv/other",
        ),
        _post(3, PICK_START - timedelta(minutes=10)),
    ]
    assert _pick_id(posts) == 3


def test_skips_already_finished():
    posts = [
        _post(
            1,
            PICK_START - timedelta(minutes=1),
            caption="Стрим окончен. Запись https://twitch.tv/videos/1",
        ),
        _post(2, PICK_START - timedelta(minutes=10)),
    ]
    assert _pick_id(posts) == 2


def test_skips_out_of_window():
    posts = [
        _post(1, PICK_START - timedelta(days=1)),
        _post(2, PICK_START - timedelta(minutes=10)),
    ]
    assert _pick_id(posts) == 2


def test_skips_excluded():
    posts = [
        _post(1, PICK_START - timedelta(minutes=1)),
        _post(2, PICK_START - timedelta(minutes=10)),
    ]
    assert _pick_id(posts, exclude_message_ids={1}) == 2


def test_text_only_post_matches():
    posts = [
        _post(
            7,
            PICK_START - timedelta(minutes=5),
            text_snapshot="Стрим онлайн https://twitch.tv/tabula",
        )
    ]
    assert _pick_id(posts) == 7


def test_skips_post_without_message_id_or_date():
    posts = [
        _post(None, PICK_START - timedelta(minutes=1)),
        _post(2, None),
        _post(3, PICK_START - timedelta(minutes=10)),
    ]
    assert _pick_id(posts) == 3


def test_returns_none_when_all_filtered():
    posts = [
        _post(1, PICK_START - timedelta(minutes=1), caption="Реклама"),
        _post(2, PICK_START - timedelta(days=2)),
    ]
    assert _pick(posts) is None


def test_aware_datetimes():
    posts = [
        _post(
            5,
            datetime(2026, 10, 1, 19, 55, tzinfo=timezone.utc),
        )
    ]
    assert _pick_id(posts) == 5
