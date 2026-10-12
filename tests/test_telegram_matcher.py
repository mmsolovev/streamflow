"""Тесты чистых функций telegram.matcher.

Запуск:
    .venv\\Scripts\\python.exe -m unittest discover -s tests -t .

aiogram, БД и сеть не требуются: matcher ничего из этого не импортирует.
"""
import unittest
from datetime import datetime, timedelta, timezone

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


class BuildChannelLinkMatcherTests(unittest.TestCase):
    def test_none_for_bad_url(self):
        self.assertIsNone(build_channel_link_matcher(None))
        self.assertIsNone(build_channel_link_matcher(""))
        self.assertIsNone(build_channel_link_matcher("twitch.tv"))
        self.assertIsNone(build_channel_link_matcher("https://twitch.tv/"))


class HasChannelLinkTests(unittest.TestCase):
    def test_announcement_shapes(self):
        m = matcher()
        cases = [
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
        ]
        for text in cases:
            with self.subTest(text=text):
                self.assertTrue(has_channel_link(text, m))

    def test_non_announcements(self):
        m = matcher()
        cases = [
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
        ]
        for text in cases:
            with self.subTest(text=text):
                self.assertFalse(has_channel_link(text, m))

    def test_none_matcher_never_matches(self):
        self.assertFalse(has_channel_link("Стрим онлайн https://twitch.tv/tabula", None))

    def test_explicit_domains(self):
        m = build_channel_link_matcher(CHANNEL_URL, ["twitch.tv", "twitch.tv"])
        self.assertTrue(has_channel_link("https://twitch.tv/tabula", m))


class IsAlreadyFinishedTests(unittest.TestCase):
    def test_finished_texts(self):
        for text in (
            "Стрим окончен. Запись https://twitch.tv/videos/1",
            "Стрим окончен.",
            "Окончилась трансляция",
            "строка со ссылкой www.twitch.tv/videos/999",
        ):
            with self.subTest(text=text):
                self.assertTrue(is_already_finished(text))

    def test_announcement_texts(self):
        for text in (
            None,
            "",
            "Стрим онлайн https://twitch.tv/tabula",
            "Стрим онлайн, запись будет завтра",
            "Начинаем стрим!",
        ):
            with self.subTest(text=text):
                self.assertFalse(is_already_finished(text))

    def test_bot_format_is_finished(self):
        # Регрессия: в подписи бота больше нет ни URL, ни слова «оконч» —
        # только заголовок «Запись стрима» и подпись ссылки. Без этого
        # маркера готовый пост выглядел бы как свежий анонс и привязался бы
        # к следующему стриму повторно.
        self.assertTrue(is_already_finished(build_finished_text(["https://twitch.tv/videos/1"])))
        text, _entities = build_finished_entities(["https://twitch.tv/videos/1"])
        self.assertTrue(is_already_finished(text))

    def test_streamer_manual_format_is_finished(self):
        # Тот же заголовок пишет стример от руки — такой пост тоже готовый.
        self.assertTrue(is_already_finished("Запись стрима:\n\n🎥TWITCH~"))

    def test_phrase_about_future_recording_is_not_finished(self):
        # «Запись» в анонсе — обычный текст, его нельзя считать меткой.
        self.assertFalse(is_already_finished("Запись стрима будет через час"))


class NormalizeTests(unittest.TestCase):
    def test_normalize_text(self):
        self.assertEqual(normalize_text("  Стрим   ОНЛАЙН\n"), "стрим онлайн")
        self.assertEqual(normalize_text(None), "")

    def test_extract_urls(self):
        urls = extract_urls("a https://twitch.tv/tabula b twitch.tv/x")
        self.assertEqual(urls, ["https://twitch.tv/tabula"])
        self.assertEqual(extract_urls("nothing here"), [])

    def test_post_text_joins_caption_and_text(self):
        post = {"caption_snapshot": "подпись", "text_snapshot": None}
        self.assertEqual(post_text(post), "подпись")
        post = {"caption_snapshot": "подпись", "text_snapshot": "текст"}
        self.assertEqual(post_text(post), "подпись\nтекст")
        self.assertEqual(post_text({}), "")

    def test_normalize_dt_variants(self):
        aware = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(normalize_dt(aware), datetime(2026, 10, 1, 12, 0))
        self.assertEqual(normalize_dt("2026-10-01T12:00:00Z"), datetime(2026, 10, 1, 12, 0))
        self.assertEqual(normalize_dt("2026-10-01T15:00:00+03:00"), datetime(2026, 10, 1, 12, 0))
        naive = datetime(2026, 10, 1, 12, 0)
        self.assertEqual(normalize_dt(naive), naive)
        self.assertIsNone(normalize_dt(None))
        self.assertIsNone(normalize_dt(""))
        self.assertIsNone(normalize_dt("не дата"))


class InWindowTests(unittest.TestCase):
    START = datetime(2026, 10, 1, 20, 0)
    END = datetime(2026, 10, 1, 22, 0)

    def test_inside(self):
        self.assertTrue(in_window(self.START - timedelta(minutes=5), started_at=self.START))
        self.assertTrue(in_window(self.START, started_at=self.START, ended_at=self.END))
        self.assertTrue(in_window(self.END + timedelta(minutes=30), started_at=self.START, ended_at=self.END))

    def test_outside(self):
        self.assertFalse(in_window(self.START - timedelta(hours=13), started_at=self.START, ended_at=self.END))
        self.assertFalse(in_window(self.END + timedelta(minutes=61), started_at=self.START, ended_at=self.END))

    def test_boundaries_inclusive(self):
        self.assertTrue(in_window(self.START - timedelta(hours=12), started_at=self.START, ended_at=self.END))
        self.assertTrue(in_window(self.END + timedelta(minutes=60), started_at=self.START, ended_at=self.END))

    def test_custom_window(self):
        posted = self.START - timedelta(minutes=10)
        self.assertTrue(in_window(posted, started_at=self.START, before_hours=0.2))
        self.assertFalse(in_window(posted, started_at=self.START, before_hours=0.1))

    def test_missing_values(self):
        self.assertFalse(in_window(None, started_at=self.START))
        self.assertFalse(in_window(self.START, started_at=None))

    def test_ended_before_started_is_tolerated(self):
        # Runtime-сессия может дать ended_at раньше started_at при кризе.
        self.assertTrue(
            in_window(self.START, started_at=self.START, ended_at=self.START - timedelta(hours=1))
        )


class InRebindWindowTests(unittest.TestCase):
    NEW_START = datetime(2026, 10, 1, 21, 5)

    def test_recent_previous_stream(self):
        previous_end = self.NEW_START - timedelta(minutes=10)
        self.assertTrue(in_rebind_window(previous_end, self.NEW_START, window_minutes=180))

    def test_old_previous_stream(self):
        previous_end = self.NEW_START - timedelta(hours=5)
        self.assertFalse(in_rebind_window(previous_end, self.NEW_START, window_minutes=180))

    def test_missing_values(self):
        self.assertFalse(in_rebind_window(None, self.NEW_START))
        self.assertFalse(in_rebind_window(self.NEW_START, None))


class HiddenLinkTests(unittest.TestCase):
    """Регрессия: ссылка на канал скрыта подписью, в тексте её нет.

    Стример пишет «💬TWITCH~» — адрес лежит в сущности text_link. Разбор
    одного текста такой пост отбрасывал как новость, и стрим терялся: в
    логах было `No Telegram announcement found`.
    """

    CAPTION = "⏺Стрим онлайн! Заканчиваем Алана, попытка номер 2 😎\n\n💬TWITCH~"
    CHANNEL = ["https://twitch.tv/tabula"]

    def test_text_alone_has_no_link(self):
        # Предположение, на котором стоит вся починка: в тексте адреса нет.
        self.assertFalse(has_channel_link(self.CAPTION, matcher()))
        self.assertNotIn("twitch.tv", self.CAPTION)

    def test_hidden_link_is_found_in_entities(self):
        self.assertTrue(has_channel_link(self.CAPTION, matcher(), self.CHANNEL))

    def test_hidden_link_survives_pick_candidate(self):
        started = datetime(2026, 10, 2, 16, 0)
        post = {
            "message_id": 4663,
            "posted_at": started - timedelta(minutes=5),
            "caption_snapshot": self.CAPTION,
            "text_snapshot": None,
            "is_forward": False,
            "link_urls": self.CHANNEL,
        }
        chosen = pick_candidate(
            [post],
            matcher=matcher(),
            started_at=started,
            ended_at=started + timedelta(hours=5),
        )
        self.assertIsNotNone(chosen, "анонс со скрытой ссылкой должен выбираться")
        self.assertEqual(chosen["message_id"], 4663)

    def test_post_without_entities_still_skipped(self):
        # Ссылок не было и в тексте нет: обычная новость остаётся новостью.
        post = {
            "message_id": 1,
            "posted_at": datetime(2026, 10, 2, 15, 55),
            "caption_snapshot": self.CAPTION,
            "text_snapshot": None,
            "is_forward": False,
        }
        chosen = pick_candidate(
            [post],
            matcher=matcher(),
            started_at=datetime(2026, 10, 2, 16, 0),
            ended_at=datetime(2026, 10, 2, 21, 0),
        )
        self.assertIsNone(chosen)

    def test_finished_marker_hidden_in_entity(self):
        # Ст��имер дописал запись скрытой ссылкой на /videos/ — пост готов,
        # переписывать его заново нельзя.
        self.assertFalse(is_already_finished(self.CAPTION))
        self.assertTrue(
            is_already_finished(self.CAPTION, ["https://www.twitch.tv/videos/2889608958"])
        )

    def test_hidden_finished_post_not_picked(self):
        post = {
            "message_id": 4663,
            "posted_at": datetime(2026, 10, 2, 15, 55),
            "caption_snapshot": self.CAPTION,
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
        self.assertIsNone(chosen)


class PickCandidateTests(unittest.TestCase):
    START = datetime(2026, 10, 1, 20, 0)
    END = datetime(2026, 10, 1, 22, 0)

    @staticmethod
    def post(message_id, posted_at, caption="Стрим онлайн https://twitch.tv/tabula", **extra):
        row = {
            "message_id": message_id,
            "posted_at": posted_at,
            "caption_snapshot": caption,
            "text_snapshot": None,
            "is_forward": False,
        }
        row.update(extra)
        return row

    def pick(self, posts, **extra):
        kwargs = {
            "matcher": matcher(),
            "started_at": self.START,
            "ended_at": self.END,
            "before_hours": 12,
            "after_minutes": 60,
        }
        kwargs.update(extra)
        return pick_candidate(posts, **kwargs)

    def pick_id(self, posts, **extra):
        """message_id выбранного поста; падение тут читаемее, чем в assert None."""
        chosen = self.pick(posts, **extra)
        if chosen is None:
            self.fail("ожидался кандидат, но вернулся None")
        return chosen["message_id"]

    def test_picks_newest_announcement(self):
        posts = [
            self.post(1, self.START - timedelta(hours=1)),
            self.post(2, self.START - timedelta(minutes=5)),
            self.post(3, self.START - timedelta(minutes=10)),
        ]
        self.assertEqual(self.pick_id(posts), 2)

    def test_empty(self):
        self.assertIsNone(self.pick([]))

    def test_skips_forwards(self):
        posts = [
            self.post(1, self.START - timedelta(minutes=5), is_forward=True),
            self.post(2, self.START - timedelta(minutes=20)),
        ]
        self.assertEqual(self.pick_id(posts), 2)

    def test_skips_posts_without_channel_link(self):
        posts = [
            self.post(1, self.START - timedelta(minutes=1), caption="Реклама магазина"),
            self.post(2, self.START - timedelta(minutes=5), caption="Стрим онлайн https://twitch.tv/other"),
            self.post(3, self.START - timedelta(minutes=10)),
        ]
        self.assertEqual(self.pick_id(posts), 3)

    def test_skips_already_finished(self):
        posts = [
            self.post(1, self.START - timedelta(minutes=1),
                      caption="Стрим окончен. Запись https://twitch.tv/videos/1"),
            self.post(2, self.START - timedelta(minutes=10)),
        ]
        self.assertEqual(self.pick_id(posts), 2)

    def test_skips_out_of_window(self):
        posts = [
            self.post(1, self.START - timedelta(days=1)),
            self.post(2, self.START - timedelta(minutes=10)),
        ]
        self.assertEqual(self.pick_id(posts), 2)

    def test_skips_excluded(self):
        posts = [
            self.post(1, self.START - timedelta(minutes=1)),
            self.post(2, self.START - timedelta(minutes=10)),
        ]
        self.assertEqual(self.pick_id(posts, exclude_message_ids={1}), 2)

    def test_text_only_post_matches(self):
        posts = [self.post(7, self.START - timedelta(minutes=5),
                           text_snapshot="Стрим онлайн https://twitch.tv/tabula")]
        self.assertEqual(self.pick_id(posts), 7)

    def test_skips_post_without_message_id_or_date(self):
        posts = [
            self.post(None, self.START - timedelta(minutes=1)),
            self.post(2, None),
            self.post(3, self.START - timedelta(minutes=10)),
        ]
        self.assertEqual(self.pick_id(posts), 3)

    def test_returns_none_when_all_filtered(self):
        posts = [
            self.post(1, self.START - timedelta(minutes=1), caption="Реклама"),
            self.post(2, self.START - timedelta(days=2)),
        ]
        self.assertIsNone(self.pick(posts))

    def test_aware_datetimes(self):
        posts = [self.post(
            5,
            datetime(2026, 10, 1, 19, 55, tzinfo=timezone.utc),
        )]
        self.assertEqual(self.pick_id(posts), 5)


if __name__ == "__main__":
    unittest.main()
