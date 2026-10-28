# Источники данных и пайплайны

## Twitch

| Что | Где | Детали |
|---|---|---|
| IRC/чат | `bot.py`, `core/` | TwitchIO 3, токен `TWITCH_TOKEN`, каналы `TWITCH_CHANNEL`/`TWITCH_CHANNELS` |
| Helix API | `pipeline/ingest/twitch_api.py`, `services/twitch_service.py` | база `https://api.twitch.tv/helix`; `Client-Id` + Bearer |
| OAuth токен приложения | `services/twitch_service.py` | `https://id.twitch.tv/oauth2/token`, `grant_type=client_credentials` |
| EventSub | `services/eventsub_service.py` | raid/shoutout, stream.online/offline, channel.update, follows |
| Модерация | `services/twitch_ban_service.py` | проверка Twitch-бана, TTL-кэш `TWITCH_BAN_CHECK_TTL_SECONDS` |

Основной канал — первый в `TWITCH_CHANNELS`; для него работают EventSub,
runtime-метрики и Telegram-анонсы.

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
  `streams`, `stream_titles`, `stream_games`, `stream_recordings`, `game_stats`,
  затем обогащение IGDB/HLTB.
- Легаси JSON (`storage/streams.json`, `storage/games.json`) поддерживается
  старыми скриптами, но не является целевым форматом.

## Google Sheets

- Сервис: `services/sheets_service.py`, `pipeline/delivery/*`,
  `pipeline/ingest/google_sheets_reader.py`.
- Авторизация — service account `config/credentials.json`; шаблон
  `config/credentials.example.json`.
- Таблица: `GAMES_SHEET_URL`; листы `ИГРЫ`, `СТРИМЫ`, `РЕЛИЗЫ`, `СОВЕТЫ`, `БОТ`.
- `sync_sheets.py` пишет из PostgreSQL; `sheets_games.py` сохраняет ручные
  колонки (оценка, статус прохождения, интерес) при безопасной синхронизации.
- Обратная синхронизация ручных колонок — `google_sheets_reader.py`.

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
  `TELEGRAM_VOD_CHECK_DELAY_SECONDS` (660 с), затем правка анонса.
- Подробности — `docs/TELEGRAM.md`.

## Runtime Stream Collector

- `runtime/collector.py` слушает EventSub `stream.online`, `stream.offline`,
  `channel.update`, follows; сэмплит зрителей и подписчиков каждые
  `STREAM_RUNTIME_SAMPLE_SECONDS` (60 с по умолчанию).
- Состояние: `storage/runtime/active_stream_session.json` и
  `completed_stream_sessions.json` — это основной источник runtime-данных.
  Таблицы `stream_runtime_samples` / `stream_runtime_buckets` объявлены в
  моделях и миграциях, но текущий коллектор в них не пишет.
- `runtime/metrics.py` пересчитывает средние/пиковые зрители, часы просмотра,
  подписки и разбивку по играм; `services/runtime.py` — общий флаг
  `BOT_ENABLED`.

## CLI-оркестраторы

| Скрипт | Назначение |
|---|---|
| `parse_streams_json.py` | TwitchTracker HTML → JSON |
| `parse_games_json.py` | HTML страниц игр → merge → JSON |
| `parse_twitchtracker.py` | HTML страниц стримов → PostgreSQL + IGDB/HLTB |
| `import_json_to_db.py` | JSON → PostgreSQL, VOD sync, обогащение |
| `import_igdb_releases.py` | IGDB → PostgreSQL (релизы) |
| `update_upcoming_release_dates.py` | обновление дат ожидаемых релизов |
| `sync_sheets.py` | PostgreSQL → Google Sheets |
| `sync_vods.py` | подтягивание VOD-ссылок из Twitch |
| `sync_wishlist.py` | синхронизация вишлиста |
| `enrich_descriptions_with_gpt.py` | PostgreSQL → LLM → PostgreSQL |

`RAWG_API_KEY` в `.env.example`/`config/settings.py` присутствует, но
активных вызовов RAWG в коде нет.
