# Источники данных и пайплайны

## Twitch

| Что | Где | Детали |
|---|---|---|
| IRC/чат | `bot.py`, `core/` | TwitchIO 3, токен `TWITCH_TOKEN`, каналы `TWITCH_CHANNEL`/`TWITCH_CHANNELS` |
| Helix API | `pipeline/ingest/twitch_api.py`, `services/twitch_service.py` | база `https://api.twitch.tv/helix`; `Client-Id` + Bearer |
| OAuth токен приложения | `services/twitch_service.py` | `https://id.twitch.tv/oauth2/token`, `grant_type=client_credentials` |
| EventSub | `services/eventsub_service.py` | raid/shoutout, stream.online/offline, channel.update, follows |
| Модерация | `services/twitch_ban_service.py` | проверка Twitch-бана, TTL-кэш `TWITCH_BAN_CHECK_TTL_SECONDS` |

Основной канал задаётся `TWITCH_PRIMARY_CHANNEL` (Tabula): для него работают
EventSub, runtime-метрики, логи чата и Telegram-анонсы. Остальные каналы из
`TWITCH_CHANNELS` используются только для проверок команд.

## IGDB

- Клиент: `pipeline/ingest/igdb_api.py`; API — `https://api.igdb.com/v4/games`.
- Авторизация: `IGDB_CLIENT_ID` / `IGDB_CLIENT_SECRET`, fallback на
  `CLIENT_ID` / `CLIENT_SECRET`.
- Ограничения: скользящее окно **4 запроса/сек**, таймаут 30 с.
- Кэш в памяти: 1 час для найденных игр, 20 с для «не найдено».
- Используется для рекомендаций (`fetch_recommendation_metadata`), релизов
  (`import_igdb_releases.py`), обогащения игр и HLTB-фолбэка.

## HowLongToBeat

- Клиент: `pipeline/ingest/hltb_client.py` + `services/hltb_service.py`
  (библиотека `howlongtobeatpy`).
- Поиск лучшего совпадения с порогом similarity `0.60`; таймаут запроса 20 с.
- Для уже обогащённых игр данные берутся из `game_metadata_hltb`; повторное
  обновление — не чаще раза в час.
- Команда `!hltb` без аргумента использует текущую категорию стрима.

## TwitchTracker

- HTML-страницы стримов скачиваются вручную в `storage/pages/stream_*.html`
  (и страницы игр — для `parse_games_json.py`).
- Парсер: `pipeline/ingest/twitchtracker_parser.py`.
- `pipeline/orchestrator/parse_twitchtracker.py`: HTML → PostgreSQL, включая
  `streams`, `stream_titles`, `stream_games`, `stream_recordings`, затем
  обогащение IGDB/HLTB.
- TT — владелец только `game_stats.avg_viewers` и `followers_per_hour`:
  остальные агрегаты (`duration_minutes`, `streams_count`, `last_stream`,
  `max_viewers`) пересчитываются из `stream_games` / `streams`. Расхождения
  TT сохраняются в `stats_change_batches.meta["tt_divergence"]`, а не
  перетирают детализацию.
- Legacy-строки `stream_games` без минут/пиков считаются «нет данных»:
  пересчёт сохраняет исторические `duration_minutes` и не уменьшает
  `max_viewers`. Массовая сверка — `aggregate_streams --all`, диагностика —
  `--drift`.
- TT показывает время канала без зоны. Все timestamp-поля конвертируются в UTC
  через `utils/time_utils.py` по `TWITCHTRACKER_TIMEZONE` (по умолчанию
  `Europe/Moscow`); дата-ключи (`parse_stream_date`,
  `game_stats.last_stream`) остаются локальными датами. Уже накопленные строки
  нормализуются `pipeline/orchestrator/normalize_time.py --apply`.
- Импорт можно выключить через `TWITCHTRACKER_IMPORT_ENABLED=false` (например,
  когда runtime-сбор уже покрывает период).
- Легаси JSON (`storage/streams.json`, `storage/games.json`) поддерживается
  старыми скриптами, но не является целевым форматом.

## Google Sheets

- Сервис: `services/sheets_service.py`, `pipeline/delivery/*`.
- Авторизация — service account `config/credentials.json`; шаблон
  `config/credentials.example.json`.
- Таблица: `GAMES_SHEET_URL`; листы `ИГРЫ`, `СТРИМЫ`, `РЕЛИЗЫ`, `СОВЕТЫ`, `БОТ`.
- `sync_sheets.py` пишет из PostgreSQL. Листы — только витрина: флаги
  «Понравилось», «Пройдено» и «Интересует» берутся из `streamer_games` и
  никогда не считываются из таблицы. Меняются они только через backend.
- Колонки с флагами закрыты protected range в Sheets: кликнуть и изменить их
  нельзя (кроме владельца таблицы, который может снять защиту).

## LLM

Провайдеры вызываются по цепочке в `services/gpt_service.py`:

1. **Gemini** — `GEMINI_API_KEY`, модель `GEMINI_MODEL`
   (по умолчанию `gemini-2.5-flash`), таймаут 30 с.
2. **OpenRouter** — `OPENROUTER_API_KEY`, `https://openrouter.ai/api/v1`,
   список бесплатных моделей, до 2 попыток на модель, пауза 3.5 с.
3. **g4f** — legacy-фолбэк без ключа.

Используется для `!gpt` (ответ в чат) и генерации коротких русских описаний
игр (`enrich_descriptions_with_gpt.py`).

## Праздники

- Runtime-чтение: `services/holiday_service.py` → PostgreSQL
  (`calendar_days`, `holidays`), кэш в памяти.
- Заполнение: `database/sync_holidays.py` из `storage/holidays.json`
  (скрипт идемпотентный).
- `CALENDARIFIC_KEY` есть в `.env.example`, но текущий код его не использует.

## Telegram

- `telegram/service.py` — long-polling aiogram.
- Включается `TELEGRAM_ENABLED=true`; нужны `TELEGRAM_BOT_TOKEN` и числовой
  `TELEGRAM_CHANNEL_ID` (`-100…`).
- После стрима создаётся задача поиска VOD с задержкой
  `TELEGRAM_VOD_CHECK_DELAY_SECONDS` (660 с), затем правка анонса. Найденная
  запись пишется в `stream_recordings` (единый реестр VOD для сайта и
  Telegram), задача хранит только `recording_id`.
- Подробности — `docs/TELEGRAM.md`.

## Runtime Stream Collector

- `runtime/collector.py` слушает EventSub `stream.online`, `stream.offline`,
  `channel.update`, follows; сэмплит зрителей и подписчиков каждые
  `STREAM_RUNTIME_SAMPLE_SECONDS` (60 с по умолчанию).
- Источник истины — PostgreSQL: `stream_runtime_sessions`,
  `stream_runtime_samples`, `stream_runtime_buckets` (см.
  `runtime/repository.py`). JSON-файлы `storage/runtime/*` больше не
  используются.
- На финализации пишутся `streams`, `stream_titles`, `stream_games`; задача
  отложенной агрегации попадает в `stream_stats_jobs` с задержкой 660 с
  (`STREAM_STATS_AGGREGATION_DELAY_SECONDS`).
- Воркер в процессе бота (`runtime/aggregation_jobs.py`) пересчитывает
  `game_stats` из `stream_games`; `avg_viewers` / `followers_per_hour`
  обновляет только TwitchTracker. Историю изменений и откат ведёт
  `services/stats_history.py`.
- `runtime/metrics.py` пересчитывает средние/пиковые зрители, часы просмотра,
  подписки и разбивку по играм; `services/runtime.py` — общий флаг
  `BOT_ENABLED`.
- Чат и успешные команды основного канала пишутся через
  `services/chat_log_service.py` в `chat_messages`, `stream_chat_participants`
  и `command_usage_logs`. Хранение сообщений — бессрочное, пока
  `CHAT_LOG_RETENTION_DAYS=0`.

## CLI-оркестраторы

| Скрипт | Назначение |
|---|---|
| `parse_streams_json.py` | TwitchTracker HTML → JSON |
| `parse_games_json.py` | HTML страниц игр → merge → JSON |
| `parse_twitchtracker.py` | HTML страниц стримов → PostgreSQL + IGDB/HLTB |
| `aggregate_streams.py` | пересчёт `game_stats`: `--due`, `--stream`, `--all`, `--drift` |
| `rollback_stats.py` | откат батча истории статистики по `--batch` или `--stream` |
| `import_json_to_db.py` | JSON → PostgreSQL, VOD sync, обогащение |
| `import_igdb_releases.py` | IGDB → PostgreSQL (релизы) |
| `update_upcoming_release_dates.py` | обновление дат ожидаемых релизов |
| `sync_sheets.py` | PostgreSQL → Google Sheets |
| `sync_vods.py` | сверка `stream_recordings` с архивом Twitch (истёкшие — `is_available=false`) |
| `normalize_time.py` | нормализация времени TwitchTracker в UTC (`--apply`) |
| `sync_wishlist.py` | синхронизация вишлиста |
| `enrich_descriptions_with_gpt.py` | PostgreSQL → LLM → PostgreSQL |

`RAWG_API_KEY` в `.env.example`/`config/settings.py` присутствует, но
активных вызовов RAWG в коде нет.
