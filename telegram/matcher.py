"""Чистые функции для поиска анонса стрима среди постов Telegram-канала.

Модуль ничего не знает про aiogram, БД и сеть: на входе текст поста и границы
времени, на выходе — решение «это анонс / это репост / это уже обработанный пост».
I/O (разбор апдейтов, запросы в БД) живёт в `handlers.py` и `announcements.py`.

Ключевая идея: опознавать анонс по **ссылке на канал**, а не по словам в подписи.
Подпись стримера меняется, ссылка на `twitch.tv/<login>` — нет.

Почему ссылки разбираются, а не ищутся подстрокой: свободный поиск
`twitch.tv/tabula` срабатывает и на `https://example.com/?ref=twitch.tv/tabula`,
и на `https://tracker.example.com/twitch.tv/tabula`. В шумном канале с репостами
и UTM-метками это даёт ложные привязки, поэтому каждая ссылка проверяется
целиком: хост должен быть ровно `twitch.tv`/`www.twitch.tv`/`m.twitch.tv`,
а последний сегмент пути — ровно логин канала.

Все datetime приводятся к naive UTC: Telegram отдаёт `message.date` со зоной,
runtime-сессии хранят ISO с `+00:00`, а колонки DateTime в БД — без зоны.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit


# Поддомены, которые не считаем мусором перед доменом канала.
# Намеренно узкий список: `tracker.example.com` сюда не входит и отсекается
# сравнением хоста, а не подстановкой в регулярку.
_ALLOWED_SUBDOMAINS = ("www", "m")

# Символы, которыми ссылка может отделяться от следующего слова в подписи.
_TRAILING_PUNCTUATION = ".,;:!?…"

# Токены для разбора ссылок: режем по пробелам и по скобкам/кавычкам,
# чтобы `(<a href="https://twitch.tv/tabula">)` распалось на саму ссылку.
_LINK_TOKEN_RE = re.compile(r"""[^\s<>"'()\[\]]+""")

# Начало схемы внутри токена. Отрезаем текст ДЛЯ схемы, но саму схему оставляем:
# иначе `Стрим онлайн!https://twitch.tv/tabula` не распарсился бы —
# `онлайн!https` невалидная схема, и urlsplit отдал бы всё в path.
_SCHEME_RE = re.compile(r"[a-z][a-z0-9+.\-]*://", re.IGNORECASE)

# Строгая схема — для extract_urls() в диагностике.
_HTTP_URL_RE = re.compile(r"""https?://[^\s<>"'()\[\]]+""", re.IGNORECASE)

# Маркеры уже обработанного поста. Список узкий намеренно.
# «оконч» покрывает «окончен», «окончилась», «окончено».
# Ссылка на /videos/ — однозначный признак готовой записи.
# «запись стрима:» — заголовок шаблона бота. Нужен потому, что подпись ссылки
# теперь «🎥TWITCH~»: ни URL, ни слова «оконч» в готовом посте не остаётся,
# и без маркера он не отличался бы от анонса следующего стрима. Тем же текстом
# пост правит стример вручную — такой пост тоже считается готовым.
# Слова «запись»/«заверш» сюда НЕ входят: «запись будет завтра» в анонсе —
# это нормальный текст, и такое ложное срабатывание потеряло бы стрим.
FINISHED_MARKERS: tuple[str, ...] = (
    "оконч",
    "twitch.tv/videos/",
    # Заголовок шаблона бота — вместе с двоеточием. Без двоеточия маркер
    # ловил бы и «Запись стрима будет через час», то есть обычный анонс.
    "запись стрима:",
)


def normalize_text(value: str | None) -> str:
    """Нижний регистр + схлопнутые пробелы. Для сравнений и поиска маркеров."""
    return " ".join((value or "").casefold().split())


def normalize_dt(value: datetime | str | None) -> datetime | None:
    """datetime | ISO-строка -> naive UTC datetime.

    Принимает то, что реально встречается в проекте: tz-aware datetime от
    Telegram, ISO-строку из runtime-сессии и naive datetime из БД.
    """
    if value is None:
        return None

    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            value = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None

    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def extract_urls(text: str | None) -> list[str]:
    """Ссылки с явной http(s)-схемой, в порядке появления."""
    return _HTTP_URL_RE.findall(text or "")


def _iter_links(text: str | None):
    """Похожие на ссылки куски текста, готовые к передаче в urlsplit."""
    for token in _LINK_TOKEN_RE.findall(text or ""):
        scheme = _SCHEME_RE.search(token)
        yield token[scheme.start():] if scheme else token


@dataclass(frozen=True)
class ChannelLinkMatcher:
    """Распознаёт ссылки именно на канал стримера.

    Не регулярка, а сравнение хоста и последнего сегмента пути: так
    `twitch.tv/tabula_news` и `twitch.tv/videos/123` отсекаются, а
    `https://example.com/?ref=twitch.tv/tabula` — тем более.
    """

    domains: tuple[str, ...]
    login: str
    hosts: frozenset[str]

    def matches(self, text: str | None) -> bool:
        for link in _iter_links(text):
            if self._matches_link(link):
                return True
        return False

    def _matches_link(self, link: str) -> bool:
        candidate = link.strip().rstrip(_TRAILING_PUNCTUATION)
        if not candidate:
            return False

        parsed = urlsplit(
            candidate if "://" in candidate else f"https://{candidate}"
        )
        host = parsed.netloc.casefold()
        if "@" in host:  # user:pass@host — ссылка ведёт не на канал
            host = host.rsplit("@", 1)[1]
        if host not in self.hosts:
            return False

        segments = [segment for segment in parsed.path.split("/") if segment]
        if not segments:
            return False

        # Последний сегмент: /tabula принимается, /tabula/videos — нет.
        return segments[-1].casefold() == self.login


def build_channel_link_matcher(
    channel_url: str | None,
    domains: list[str] | tuple[str, ...] | None = None,
) -> ChannelLinkMatcher | None:
    """`https://twitch.tv/tabula` -> ChannelLinkMatcher.

    Возвращает None, если `channel_url` не разбирается — тогда вызывающий код
    работает без matcher'а, и посты в БД пишутся, но никогда не привязываются.
    """
    if not channel_url:
        return None

    parsed = urlsplit(channel_url.strip())
    segments = [segment for segment in parsed.path.split("/") if segment]
    if not parsed.netloc or not segments:
        return None

    domain = parsed.netloc.casefold()
    clean_domains = tuple(
        dict.fromkeys(
            d.strip().casefold() for d in (domains or [domain]) if d and d.strip()
        )
    ) or (domain,)

    hosts = set()
    for candidate in clean_domains:
        hosts.add(candidate)
        for subdomain in _ALLOWED_SUBDOMAINS:
            hosts.add(f"{subdomain}.{candidate}")

    return ChannelLinkMatcher(
        domains=clean_domains,
        login=segments[-1].casefold(),
        hosts=frozenset(hosts),
    )


def has_channel_link(
    text: str | None,
    matcher: ChannelLinkMatcher | None,
    link_urls=None,
) -> bool:
    """Есть ли в посте ссылка на канал стримера.

    Проверяются и текст, и адреса из entities: стример пишет ссылку скрытой
    подписью, и в тексте её нет вообще. Без `link_urls` такой анонс
    выглядел бы как новость и терял бы стрим.

    Ссылка на VOD (`twitch.tv/videos/123`) и на другой канал
    (`twitch.tv/tabula_news`) сюда не подходят.
    """
    if matcher is None:
        return False
    if matcher.matches(text):
        return True
    return any(matcher.matches(url) for url in (link_urls or ()))


def is_already_finished(text: str | None, link_urls=None) -> bool:
    """Пост уже содержит отметку о завершении или готовую запись.

    Адреса из entities смотрятся здесь же, что и в `has_channel_link`: ссылка
    на `/videos/` может быть скрытой подписью, и по одному тексту пост
    выглядел бы незавершённым — бот переписал бы заново то, что стример
    уже оформил руками.
    """
    haystacks = [normalize_text(text)] if text else []
    haystacks.extend(normalize_text(url) for url in (link_urls or ()))

    for normalized in haystacks:
        if normalized and any(marker in normalized for marker in FINISHED_MARKERS):
            return True

    return False


def post_text(post: dict) -> str:
    """Весь текст поста: подпись и текст вместе.

    В Telegram они взаимоисключающие, но в таблице хранятся обе колонки,
    и при разборе апдейта неизвестно ещё, какая придёт.
    """
    parts = [
        str(part)
        for part in (post.get("caption_snapshot"), post.get("text_snapshot"))
        if part
    ]
    return "\n".join(parts)


def in_window(
    posted_at: datetime | str | None,
    *,
    started_at: datetime | str | None,
    ended_at: datetime | str | None = None,
    before_hours: float = 12.0,
    after_minutes: float = 60.0,
) -> bool:
    """Попадает ли пост в окно стрима. Границы включительные.

    Анонс обычно выходит за несколько минут до старта, поэтому левая граница
    намеренно широкая; сужается настройкой `TELEGRAM_MATCH_WINDOW_BEFORE_HOURS`.
    """
    posted = normalize_dt(posted_at)
    start = normalize_dt(started_at)
    if posted is None or start is None:
        return False

    end = normalize_dt(ended_at) or start
    if start > end:
        start, end = end, start

    lower = start - timedelta(hours=before_hours)
    upper = end + timedelta(minutes=after_minutes)
    return lower <= posted <= upper


def in_rebind_window(
    previous_ended_at: datetime | str | None,
    new_started_at: datetime | str | None,
    window_minutes: float = 180.0,
) -> bool:
    """Можно ли считать новый стрим продолжением анонса предыдущего.

    Сценарий: трансляция падает, стример перезапускает broadcast, нового анонса
    он не публикует. Если предыдущий стрим закончился недавно, новый относится
    к тому же посту, и его VOD станет второй ссылкой в том же тексте.
    """
    previous_end = normalize_dt(previous_ended_at)
    new_start = normalize_dt(new_started_at)
    if previous_end is None or new_start is None:
        return False

    return previous_end >= new_start - timedelta(minutes=window_minutes)


def pick_candidate(
    posts,
    *,
    matcher: ChannelLinkMatcher | None,
    started_at: datetime | str | None,
    ended_at: datetime | str | None = None,
    before_hours: float = 12.0,
    after_minutes: float = 60.0,
    exclude_message_ids=None,
) -> dict | None:
    """Самый свежий пост-кандидат для анонса стрима, либо None.

    Фильтры по порядку важности:
      1. репост — в канале их много, анонсами они не являются;
      2. отсутствие ссылки на канал — отсекает новости и рекламу;
      3. `is_already_finished` — не правим пост дважды и не затираем
         ручную правку стримера;
      4. окно времени стрима;
      5. `exclude_message_ids` — уже привязанные посты (защита от повторов).

    Ссылки и признаки готовности ищутся и в тексте, и в `link_urls`: у поста
    со скрытой ссылкой в тексте адреса нет, и без второго источника анонс
    отсеивался бы как новость.
    """
    excluded = set(exclude_message_ids or ())
    best: dict | None = None
    best_posted_at: datetime | None = None

    for post in posts:
        message_id = post.get("message_id")
        if message_id is None or message_id in excluded:
            continue

        if post.get("is_forward"):
            continue

        text = post_text(post)
        link_urls = post.get("link_urls") or ()
        if not has_channel_link(text, matcher, link_urls):
            continue

        if is_already_finished(text, link_urls):
            continue

        posted_at = normalize_dt(post.get("posted_at"))
        if posted_at is None:
            continue

        if not in_window(
            posted_at,
            started_at=started_at,
            ended_at=ended_at,
            before_hours=before_hours,
            after_minutes=after_minutes,
        ):
            continue

        if best_posted_at is None or posted_at > best_posted_at:
            best, best_posted_at = post, posted_at

    return best


__all__ = [
    "ChannelLinkMatcher",
    "FINISHED_MARKERS",
    "build_channel_link_matcher",
    "extract_urls",
    "has_channel_link",
    "in_rebind_window",
    "in_window",
    "is_already_finished",
    "normalize_dt",
    "normalize_text",
    "pick_candidate",
    "post_text",
]
