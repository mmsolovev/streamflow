import os
from dotenv import load_dotenv


load_dotenv()

TWITCH_TOKEN = os.getenv("TWITCH_TOKEN")
TWITCH_ACCESS_TOKEN = TWITCH_TOKEN.removeprefix("oauth:") if TWITCH_TOKEN else None
TWITCH_REFRESH_TOKEN = os.getenv("TWITCH_REFRESH_TOKEN")
TWITCH_NICK = os.getenv("TWITCH_NICK")
TWITCH_CHANNEL = os.getenv("TWITCH_CHANNEL")


def _parse_channels(value: str | None) -> list[str]:
    if not value:
        return []
    channels = []
    for token in value.split(","):
        token = token.strip()
        if not token:
            continue
        token = token.removeprefix("#")
        channels.append(token)
    return channels


def _parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [token.strip() for token in value.split(",") if token.strip()]


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None or not value.strip():
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on", "y"}


# Можно подключаться сразу к нескольким каналам (IRC). Первый в списке — основной:
# для EventSub/статистики/анонсов. Второй и далее — только чат/команды.
_channels_from_env = _parse_channels(os.getenv("TWITCH_CHANNELS"))
if _channels_from_env:
    TWITCH_CHANNELS = _channels_from_env
else:
    TWITCH_CHANNELS = _parse_channels(TWITCH_CHANNEL) if TWITCH_CHANNEL else []

TWITCH_PRIMARY_CHANNEL = TWITCH_CHANNELS[0] if TWITCH_CHANNELS else TWITCH_CHANNEL

# Каналы, в которых бот отправляет сообщения через Send Chat Message API
# (появляется Chat Bot Badge). Пустое значение = функция выключена.
TWITCH_BOT_BADGE_CHANNELS = _parse_channels(os.getenv("TWITCH_BOT_BADGE_CHANNELS"))

CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
IGDB_CLIENT_ID = os.getenv("IGDB_CLIENT_ID") or CLIENT_ID
IGDB_CLIENT_SECRET = os.getenv("IGDB_CLIENT_SECRET") or CLIENT_SECRET
BOT_ID = os.getenv("BOT_ID")
RAWG_API_KEY = os.getenv("RAWG_API_KEY")
GAMES_SHEET_URL = os.getenv("GAMES_SHEET_URL")
STREAM_RUNTIME_SAMPLE_SECONDS = int(os.getenv("STREAM_RUNTIME_SAMPLE_SECONDS", "60"))

BOT_PREFIX = "!"
SIGN="MrDestructoid"
COOLDOWN = 60
# Bootstrap-идентификатор владельца. Роль хранится в users.role; env нужен,
# чтобы восстановить доступ, если роль случайно потеряна.
OWNER_TWITCH_USER_ID = os.getenv("OWNER_TWITCH_USER_ID", "137727939").strip()
OWNER_TWITCH_LOGIN = os.getenv("OWNER_TWITCH_LOGIN", "mishgan_sol").strip()

TWITCH_BAN_CHECK_TTL_SECONDS = int(os.getenv("TWITCH_BAN_CHECK_TTL_SECONDS", "600"))
TWITCH_BAN_SYNC_INTERVAL_SECONDS = int(os.getenv("TWITCH_BAN_SYNC_INTERVAL_SECONDS", "900"))
TWITCH_BAN_FAIL_OPEN = os.getenv("TWITCH_BAN_FAIL_OPEN", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

# Legacy-списки. Используются только одноразовым database/seed_roles.py и
# больше не участвуют в проверках прав. После seed их можно удалить из env.
ADMINS = ["mishgan_sol", "tabula", "orfeylefontu"]
ALLOWED_USERS = {"mishgan_sol", "tabula", "orfeylefontu", "eternalchilll", "wraith8", "kampacha", "angrys2l"}
RECOMMENDATIONS_LIMIT = int(os.getenv("RECOMMENDATIONS_LIMIT", "10"))
RECOMMENDATIONS_BANNED_USERS = {
    user.strip().casefold()
    for user in os.getenv("RECOMMENDATIONS_BANNED_USERS", "").split(",")
    if user.strip()
}
RECOMMENDATIONS_STREAMER_LOGIN = os.getenv("RECOMMENDATIONS_STREAMER_LOGIN", "tabula")
RECOMMENDATIONS_STREAMER_DISPLAY_NAME = os.getenv("RECOMMENDATIONS_STREAMER_DISPLAY_NAME", "Tabula")

# Логины аккаунтов, которым разрешён расширенный OAuth-вход на сайте
# (/auth/streamer/*) для получения «стримерского» токена с доп. scopes.
# Чтобы добавить ещё стримеров — либо перечисли их через запятую в env
# STREAMER_LOGINS, либо допиши логин в список ниже. Сравнение без учёта
# регистра (casefold).
STREAMER_LOGINS = _parse_csv(os.getenv("STREAMER_LOGINS")) or [RECOMMENDATIONS_STREAMER_LOGIN]
# Необязательный override. 0 = резолвить основного стримера по
# RECOMMENDATIONS_STREAMER_LOGIN из БД.
SHEETS_STREAMER_ID = int(os.getenv("SHEETS_STREAMER_ID", "0"))
RECOMMENDATION_SHEETS_SYNC_DEBOUNCE_SECONDS = int(os.getenv("RECOMMENDATION_SHEETS_SYNC_DEBOUNCE_SECONDS", "15"))

SPREADSHEET_NAME = "Tabula Streams"
GAMES_SHEET_NAME = "ИГРЫ"
STREAMS_SHEET_NAME = "СТРИМЫ"
RELEASES_SHEET_NAME = "РЕЛИЗЫ"
RECOMMENDATIONS_SHEET_NAME = "СОВЕТЫ"
BOT_INFO_SHEET_NAME = "БОТ"


# =====================================================
# TELEGRAM: правка анонсов стримов при появлении записи
# =====================================================
# Пакет telegram/ читает эти переменные напрямую, импортируя модуль
# (config.settings), а не отдельный telegram.settings, — так же, как это
# делают services/* и runtime/*.

# Главный переключатель. Пока выключен — ни long-poll, ни правки постов.
TELEGRAM_ENABLED = _parse_bool(os.getenv("TELEGRAM_ENABLED"), default=False)
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Один канал: @username или -100xxxxxxxxxx. Несколько — фаза 2.
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")

# Через сколько секунд после окончания стрима проверять наличие VOD.
TELEGRAM_VOD_CHECK_DELAY_SECONDS = int(os.getenv("TELEGRAM_VOD_CHECK_DELAY_SECONDS", "660"))

# Как часто поллер опрашивает БД на предмет задач с check_at <= now().
TELEGRAM_VOD_POLL_INTERVAL_SECONDS = int(os.getenv("TELEGRAM_VOD_POLL_INTERVAL_SECONDS", "60"))

# Повторы при ошибках инфраструктуры (сеть, 5xx), не при отсутствии VOD.
TELEGRAM_VOD_MAX_ATTEMPTS = int(os.getenv("TELEGRAM_VOD_MAX_ATTEMPTS", "5"))

# Окно, в котором ищем анонс относительно стрима.
TELEGRAM_MATCH_WINDOW_BEFORE_HOURS = int(os.getenv("TELEGRAM_MATCH_WINDOW_BEFORE_HOURS", "12"))
TELEGRAM_MATCH_WINDOW_AFTER_MINUTES = int(os.getenv("TELEGRAM_MATCH_WINDOW_AFTER_MINUTES", "60"))

# Если трансляция падала и broadcast перезапускался — насколько поздно
# предыдущий стрим ещё считается частью того же анонса.
TELEGRAM_REBIND_WINDOW_MINUTES = int(os.getenv("TELEGRAM_REBIND_WINDOW_MINUTES", "180"))

# Домены, на которые смотрим в тексте поста при поиске анонса.
TELEGRAM_LINK_DOMAINS = _parse_csv(os.getenv("TELEGRAM_LINK_DOMAINS")) or ["twitch.tv"]

# Ссылка на канал выводится из TWITCH_PRIMARY_CHANNEL, чтобы не дублировать
# её в .env и не разъехаться с фактическим каналом стримов.
TELEGRAM_CHANNEL_URL = (
    f"https://twitch.tv/{TWITCH_PRIMARY_CHANNEL.casefold()}" if TWITCH_PRIMARY_CHANNEL else None
)
