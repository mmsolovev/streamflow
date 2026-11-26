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

- HTML-страницы стримов скачиваются вручную в `storage/pages/streams_tt/stream_*.html`
  (сводные страницы игр — в `storage/pages/games_page*.html`).
- Парсер: `pipeline/ingest/twitchtracker_parser.py`.
- `pipeline/orchestrator/parse_twitchtracker.py`: HTML → PostgreSQL, включая
  `streams`, `stream_titles`, `stream_games`, `stream_recordings`, затем
  обогащение IGDB/HLTB.
- Архив страниц `streams_tt` импортируется отдельным скриптом
  `python -m pipeline.orchestrator.import_twitchtracker_stream_pages`.
  По умолчанию это dry-run; `--apply` разрешает запись. Сопоставление игры:
  Twitch category ID → имя/`game_aliases`; неоднозначные и неизвестные игры
  блокируют применение, новые игры автоматически не создаются. Совпадающие
  ID сохраняются в `games.twitch_category_id`, отличающиеся безопасные имена —
  в `game_aliases`. Старт существующего стрима не перезаписывается; пустые
  поля заполняются, существующие ненулевые метрики при расхождении сохраняются
  и попадают в отчёт. История `stream_titles` добавляется идемпотентно.
- Сводка games-page хранится отдельно в `game_metadata_twitchtracker`.
  `game_stats` вычисляется из `stream_games` / `streams`: среднее зрителей —
  взвешенное по длительности, followers/hour — суммарные подписчики на часы
  категории. При неполных деталях старое вычисленное значение не затирается;
  расхождения со сводкой TT сохраняются в
  `stats_change_batches.meta["tt_divergence"]`.
- При конфликте уже заполненных stream/game полей импорт сохраняет текущее
  значение и выводит расхождение; пустые поля заполняются из TT. Перед
  применением нужно просмотреть dry-run.
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

## Twitch Media

- Публичные каталоги сайта читают `stream_recordings` и `clips` через
  `/api/v1/media/recordings` и `/api/v1/media/clips`; страницы не обращаются к
  Twitch API напрямую.
- VOD синхронизируются существующим архивным worker-ом, который также
  обновляет заголовок, thumbnail и количество просмотров.
- `ClipArchiveSyncWorker` во время эфира догоняет новые клипы с перекрывающимся
  временным курсором (по умолчанию каждые 12 минут). Через 12 минут после
  финализации runtime-сессии ставится повторная проверка клипов этого стрима.
  Вне эфира новые клипы обнаруживаются примерно раз в 6 часов, в том числе
  созданные позже из VOD.
- Во время эфира просмотры популярных и свежих клипов обновляются раз в час.
- Вне эфира раз в 12 часов обновляются метрики популярных и свежих клипов, а
  также небольшой пакет давно не проверявшихся записей. Ошибки Twitch не
  двигают курсор; повторные запросы безопасны благодаря `external_id`.
- Первичный полный бэкфилл — `python database/sync_clips.py`; штатный worker
  не повторяет его целиком и не создаёт Twitch-запрос на каждый просмотр сайта.
- Фото новых Telegram-анонсов скачиваются в `MEDIA_STORAGE_DIR`; медиакаталог
  использует их как fallback-превью связанных VOD. Ручные и IGDB-обложки игр,
  ручные превью VOD и иконки соцсетей связываются с `media_assets` отдельными
  FK-таблицами.

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
- После стрима создаётся задача поиска VOD с задержкой из
  `telegram_post_edit_settings.delay_seconds` (по умолчанию 660 с), затем
  правка анонса. Все найденные записи broadcast пишутся в `stream_recordings`
  (единый реестр VOD для сайта и Telegram), задача хранит только `recording_id`.
- Архивная синхронизация каждые
  `TWITCH_VOD_ARCHIVE_SYNC_INTERVAL_SECONDS` (6 часов по умолчанию) сверяет
  доступность VOD с Twitch. Строки, на которые ссылаются новостные анонсы,
  остаются недоступными tombstone; остальные устаревшие строки удаляются.
- Подробности — `docs/TELEGRAM.md`.

## Runtime Stream Collector

- `runtime/collector.py` слушает EventSub `stream.online`, `stream.offline`,
  `channel.update`, follows; сэмплит зрителей и подписчиков каждые
  `STREAM_RUNTIME_SAMPLE_SECONDS` (60 с по умолчанию).
- Источник истины — PostgreSQL: `stream_runtime_sessions`,
  `stream_runtime_samples`, `stream_runtime_buckets` (см.
  `runtime/repository.py`). JSON-файлы `storage/runtime/*` больше не
  используются.
- `GET /streams/current` собирает live-островок из свежей сессии `collecting`
  и её runtime-сэмплов. Незавершённая запись сессии исключается из истории
  `/streams`, чтобы не дублировать её; после финализации она снова становится
  обычной строкой списка. Live endpoint скрывает данные, если последний сэмпл
  старше порога свежести (не менее 3 минут).
- `GET /games/current-stream` считает время по каждой Twitch-категории из
  runtime-сэмплов. Островки остаются до завершения задачи `stream_stats_jobs`,
  чтобы перекрыть задержку агрегации `game_stats`; схема БД не меняется.
- На финализации пишутся `streams`, `stream_titles`, `stream_games`; задача
  отложенной агрегации попадает в `stream_stats_jobs` с задержкой 660 с
  (`STREAM_STATS_AGGREGATION_DELAY_SECONDS`).
- Воркер в процессе бота (`runtime/aggregation_jobs.py`) пересчитывает
  `game_stats` из `stream_games`, включая взвешенное среднее зрителей и
  followers/hour; исходная сводка TwitchTracker хранится отдельно.
- При смене категории runtime использует Twitch category ID из EventSub и
  Helix `GET /games?id=...`. Если Helix вернул `igdb_id`, IGDB ищется по
  точному ID; только при отсутствии связи применяется поиск по названию.
  Неигровые категории (например, Just Chatting) в IGDB не ищутся. Исторические
  и новые Twitch ID привязаны к игре через `game_twitch_categories`; уже
  существующая привязка автоматически не переназначается.
- Историю изменений и откат ведёт `services/stats_history.py`.
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
| `import_twitchtracker_stream_pages.py` | `streams_tt/*.html` → preflight-импорт; `--authoritative --page <имя> --apply` заменяет данные конкретного стрима значениями TwitchTracker и убирает категории, отсутствующие на TT-странице |
| `aggregate_streams.py` | пересчёт `game_stats`: `--due`, `--stream`, `--all`, `--drift` |
| `rollback_stats.py` | откат батча истории статистики по `--batch` или `--stream` |
| `import_json_to_db.py` | JSON → PostgreSQL, VOD sync, обогащение |
| `import_igdb_releases.py` | IGDB → PostgreSQL (релизы) |
| `update_upcoming_release_dates.py` | обновление дат ожидаемых релизов |
| `sync_sheets.py` | PostgreSQL → Google Sheets |
| `sync_vods.py` | сверка `stream_recordings` с архивом Twitch (истёкшие скрываются/удаляются); также запускается в bot worker и перед sync листа «Стримы» |
| `normalize_time.py` | нормализация времени TwitchTracker в UTC (`--apply`) |
| `sync_wishlist.py` | синхронизация вишлиста |
| `enrich_descriptions_with_gpt.py` | PostgreSQL → LLM → PostgreSQL |

`RAWG_API_KEY` в `.env.example`/`config/settings.py` присутствует, но
активных вызовов RAWG в коде нет.
