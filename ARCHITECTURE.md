# Архитектура проекта

## 1. Общая структура (System Context)

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        ВНЕШНИЕ СИСТЕМЫ                                      │
│                                                                             │
│  ┌──────────┐  ┌──────────┐  ┌───────┐  ┌───────────────┐  ┌──────────┐   │
│  │ Twitch   │  │ IGDB API │  │ HLTB  │  │ Google Sheets  │  │ g4f/GPT  │   │
│  │ IRC/API  │  │ (игры)   │  │(время │  │ (UI/хранение)  │  │(описания)│   │
│  │ /EventSub│  │          │  │прох.) │  │                │  │          │   │
│  └────┬─────┘  └────┬─────┘  └───┬───┘  └───────┬───────┘  └─────┬────┘   │
│       │             │            │               │                │        │
└───────┼─────────────┼────────────┼───────────────┼────────────────┼────────┘
        │             │            │               │                │
   ┌────▼─────────────▼────────────▼───────────────▼────────────────▼────┐
   │                            ПРОЕКТ                                     │
   │                                                                       │
   │  ┌──────────────────────────────────────────────────────────┐        │
   │  │                    PIPELINE (ETL)                        │        │
   │  │  ┌──────────┐  ┌──────────┐  ┌────────┐  ┌──────────┐  │        │
   │  │  │  INGEST   │  │ TRANSFORM│  │  LOAD   │  │ DELIVERY │  │        │
   │  │  │ (сбор)    │─►│ (чистка, │─►│ (запись │─►│ (выгрузка)│  │        │
   │  │  │           │  │ обогащ.) │  │ в SQLite)│  │          │  │        │
   │  │  └──────────┘  └──────────┘  └────────┘  └──────────┘  │        │
   │  │       ▲                            │                      │        │
   │  │       │   ┌────────────────────────┘                      │        │
   │  │       │   │  SQLite (storage/streams.db)                  │        │
   │  │       └───┴───────────────────────────────────────────────┘        │
   │  └──────────────────────────────────────────────────────────┘        │
   │                                                                       │
   │  ┌──────────────────────────────────────────────────────┐            │
   │  │              CONSUMERS (Бот и сервисы)                │            │
   │  │                                                       │            │
   │  │  ┌────────────┐  ┌──────────────┐  ┌───────────────┐ │            │
   │  │  │  Twitch IRC │  │   EventSub   │  │  Runtime       │ │            │
   │  │  │  (bot.py,   │  │  (eventsub_  │  │  Stream        │ │            │
   │  │  │   core/)    │  │   service)   │  │  Collector     │ │            │
   │  │  │  ◄─чат      │  │  ◄─Live-ивенты│  │  (live-       │ │            │
   │  │  │  команды    │  │  (raid,start,│  │   метрики)     │ │            │
   │  │  │             │  │  channel_upd)│  │               │ │            │
   │  │  └────────────┘  └──────────────┘  └───────────────┘ │            │
   │  └──────────────────────────────────────────────────────┘            │
   │                                                                       │
   │  ┌──────────────────────────────────────────────────┐                │
   │  │              ORCHESTRATOR (CLI)                   │                │
   │  │  import_json_to_db  │  sync_sheets  │  import_   │                │
   │  │  parse_streams_json │               │  igdb_     │                │
   │  │  parse_games_json   │               │  releases  │                │
   │  │                     │               │            │                │
   │  │  enrich_descriptions_with_gpt                     │                │
   │  └──────────────────────────────────────────────────┘                │
   └───────────────────────────────────────────────────────────────────────┘
```

---

## 2. Слой Pipeline (ETL)

```
pipeline/
│
├── ingest/                          # Сбор — читает внешние источники
│   ├── twitch_api.py                #   Twitch Helix API: VOD list, channel info
│   ├── igdb_api.py                  #   IGDB API: game metadata, upcoming releases
│   │                                #     + sliding-window rate limiter (4 req/s)
│   │                                #     + in-memory TTL cache (1h)
│   ├── hltb_client.py               #   HowLongToBeat: время прохождения игры
│   ├── twitchtracker_parser.py      #   TwitchTracker HTML→dataclass (стримы, игры)
│   └── google_sheets_reader.py      #   Google Sheets: ручные колонки (liked,completed)
│
├── transform/                       # Трансформация — чистые функции, без I/O
│   ├── utils_transform.py           #   Нормализация строк, жанров, дедупликация
│   ├── streams_transform.py         #   Вычисление жанров стрима по заголовку
│   │                                #   VOD matching (по дате ±1д, пересечению названий)
│   ├── games_transform.py           #   Решение, какие поля GameMeta нужно обогатить
│   ├── igdb_transform.py            #   Парсинг IGDB payload: даты, платформы, жанры
│   ├── twitchtracker_transform.py   #   Склейка дубликатов игр из нескольких HTML-страниц
│   ├── sheets_transform.py          #   Нормализация для Google Sheets (padding/bool)
│   └── recommendations_transform.py #   Статусы рекомендаций (upcoming/released/streamed)
│
├── load/                            # Загрузка — пишет в SQLite (через SQLAlchemy)
│   ├── load_streams.py              #   Stream upsert, VOD sync, genres_text
│   ├── load_participants.py         #   Participant get_or_create, парсинг @username
│   ├── load_stream_games.py         #   StreamGame association (порядок игр в стриме)
│   ├── load_games.py                #   Game get_or_create
│   ├── load_game_meta.py            #   GameMeta: обогащение (HLTB, IGDB) + ручные поля
│   ├── load_game_stats.py           #   GameStats upsert (из TwitchTracker)
│   └── load_recommendations.py      #   RecommendedGame CRUD + lifecycle (статусы)
│
├── delivery/                        # Доставка — выгружает данные вовне
│   ├── sheets_utils.py              #   Shared: upload_table, get_or_create_worksheet
│   ├── sheets_header.py             #   Шапка "Tabula Streams" (мерж ячеек, тема)
│   ├── sheets_games.py              #   Лист ИГРЫ (sync + safe-sync с сохранением ручных колонок)
│   ├── sheets_streams.py            #   Лист СТРИМЫ
│   ├── sheets_releases.py           #   Лист РЕЛИЗЫ (с обратным отсчётом)
│   ├── sheets_recommendations.py    #   Лист СОВЕТЫ
│   ├── sheets_bot_info.py           #   Лист БОТ (CHAT_COMMANDS.txt)
│   └── json_twitchtracker.py        #   JSON legacy-формат (storage/streams.json, games.json)
│
└── orchestrator/                    # Оркестрация — CLI-сборки слоёв в рабочие скрипты
    ├── parse_streams_json.py        #   HTML → JSON (Ingest → Delivery)
    ├── parse_games_json.py          #   HTML(несколько) → merge → JSON
    ├── import_json_to_db.py         #   JSON → SQLite + VOD sync + HLTB/IGDB enrich + genres
    ├── import_igdb_releases.py      #   IGDB API → SQLite (новые релизы)
    ├── sync_sheets.py               #   SQLite → Google Sheets (все листы)
    └── enrich_descriptions_with_gpt.py # SQLite → GPT → SQLite (описания на русском)
```

### Data Flow Pipeline

```
TwitchTracker HTML ──► parse_stream_json ──► storage/streams.json ──┐
                       parse_games_json  ──► storage/games.json  ───┤
                                                                     │
IGDB API ──► import_igdb_releases ──► SQLite (recommended_games)     │
                                                                     │
                          ┌──────────────────────────────────────────┘
                          ▼
            import_json_to_db.py
              │
              ├── sync_streams()          ← streams.json
              ├── sync_game_stats()        ← games.json
              ├── sync_stream_vod_urls()   ← Twitch API
              ├── enrich_game_meta()       ← HLTB + IGDB
              └── compute_stream_genres()  ← по заголовкам
                          │
                          ▼
                   SQLite (streams.db)
                          │
              ┌───────────┴───────────┐
              ▼                       ▼
   enrich_descriptions_gpt    sync_sheets.py
   (GPT → short_description)    │
                                ├── sheets_games         → лист "ИГРЫ"
                                ├── sheets_streams       → лист "СТРИМЫ"
                                ├── sheets_releases      → лист "РЕЛИЗЫ"
                                ├── sheets_recommendations → лист "СОВЕТЫ"
                                └── sheets_bot_info      → лист "БОТ"
```

---

## 3. Слой Consumers (Бот и runtime-сервисы)

```
bot.py ───── точка входа
│
└── core/
    ├── bot.py                     # TwitchIO Bot: IRC, EventSub, kill-switch (!отбой/!старт)
    ├── context.py                 # SafeContext: цензура исходящих сообщений
    └── registry.py                # Загрузка всех команд (импорт + bot.add_command)

commands/                          # Обработчики чат-команд
  ├── help.py                      #   !команды (справочная)
  ├── info.py                      #   !инфо (локальная справка)
  ├── games.py                     #   !игры (статистика по игре)
  ├── streams.py                   #   !стримы (статистика стрима)
  ├── hltb.py                      #   !hltb (время прохождения)
  ├── holiday.py                   #   !праздник
  ├── gpt.py                       #   !gpt (GPT-ответ)
  ├── recommendations.py           #   !рек (предложить/проголосовать)
  ├── r.py                         #   !r (смена раскладки)
  ├── timer.py                     #   !таймер
  ├── time_runtime.py              #   !время (продолжительность стрима)
  ├── admin.py                     #   !отбой / !старт
  └── movies.py                    #   !фильмы

services/                          # Бизнес-логика runtime
  ├── command_registry.py           # Реестр команд (COMMANDS_INFO, нормализация доступа)
  ├── deferred_service.py           # RecommendationSheetsSyncScheduler (debounced sync)
  ├── eventsub_service.py           # EventSub WebSocket: raid, shoutout, channel.update
  ├── runtime_stream_collector.py   # **Live-метрики**: viewer samples, follower tracking,
  │                                 #   game segments, 10-min buckets (TwitchTracker-like)
  ├── runtime.py                    # BOT_ENABLED flag (kill-switch)
  ├── chat_service.py               # Логика чата (сообщения о смене игры)
  ├── games_service.py              # Поиск игры по названию
  ├── streams_service.py            # Поиск стрима по дате
  ├── recommendations_service.py    # Логика голосования и статусов рекомендаций
  ├── gpt_service.py                # GPT-генерация (g4f)
  ├── hltb_service.py               # HowLongToBeat (обёртка для команд)
  ├── holiday_service.py            # Праздники (Calendarific API)
  ├── igdb_service.py               # IGDB auth (build_igdb_auth_headers)
  ├── sheets_service.py             # Google Sheets client (get_client)
  ├── twitch_service.py             # Twitch API helpers (runtime)
  ├── info_service.py               # !инфо (info.json lookup)
  ├── reply_layout_service.py       # !r (смена раскладки клавиатуры)
  ├── lost_movie_service.py         # !фильмы
  ├── openrouter_service.py         # Альтернативный GPT-клиент
  └── timer_service.py              # !таймер (обратный отсчёт)
```

---

## 4. База данных (SQLite)

```
┌───────────────────────────────────────────────────────────────────┐
│                                                                   │
│  games                   streams              participants        │
│  ┌──────────────┐       ┌──────────────┐     ┌──────────────┐    │
│  │ id (PK)      │       │ id (PK)      │     │ id (PK)      │    │
│  │ name (UQ,IX) │◄──┐   │ external_id  │     │ name (UQ,IX) │    │
│  └──────┬───────┘   │   │ date (IX)    │     │ display_name │    │
│         │           │   │ duration     │     │ twitch_url   │    │
│         │           │   │ avg_viewers  │     └──────┬───────┘    │
│         │           │   │ max_viewers  │            │            │
│  games_meta         │   │ followers    │     stream_participants │
│  ┌──────────────┐   │   │ views        │     ┌──────────────┐    │
│  │ game_id (PK) │   │   │ title        │     │ stream_id    │────┼──┐
│  │ liked        │   │   │ vod_url      │     │ participant_id│   │  │
│  │ completed    │   │   │ genres_text  │     └──────────────┘   │  │
│  │ hltb_hours   │   │   └──────┬───────┘                        │  │
│  │ steam_url    │   │          │                                │  │
│  │ platforms_txt│   │  stream_games (порядок игр в стриме)      │  │
│  │ genres_text  │   │  ┌──────────────┐                         │  │
│  └──────────────┘   └──┤ stream_id    │                         │  │
│                        │ game_id      │◄────────────────────────┘  │
│  games_stats           │ position     │                            │
│  ┌──────────────┐      └──────────────┘                            │
│  │ game_id (PK) │                                                 │
│  │ period (PK)  │     recommended_games                            │
│  │ hours_streamd│     ┌──────────────────┐                        │
│  │ streams_count│     │ id (PK)          │                        │
│  │ last_stream  │     │ normalized_name  │◄─── matched_game_id ───┘
│  └──────────────┘     │ title            │                        │
│                       │ status (IX)      │── "upcoming"/"released" │
│  recommended_game_votes│ release_date    │                        │
│  ┌──────────────────┐ │ description_short│◄── GPT-generated       │
│  │ id (PK)          │ │ steam_url        │                        │
│  │ recommended_game │ │ rating_text      │                        │
│  │ user_login       │ │ cover_url        │                        │
│  │ created_at       │ │ source_name      │── "igdb"/"chat"       │
│  └──────────────────┘ │ streamer_interested│                      │
│                 ┌─────┤ created_at       │                        │
│                 │     │ updated_at       │                        │
│                 │     └──────────────────┘                        │
│                 │               │                                 │
│                 └───────────────┘                                 │
└───────────────────────────────────────────────────────────────────┘
```

---

## 5. Data Flow runtime (EventSub live-сбор)

```
Twitch EventSub WebSocket
       │
       ├── channel.update ──────────────────────────► eventsub_service
       │     (смена игры/тайтла)                         │
       │                                                ├──► RuntimeStreamCollector.handle_channel_update()
       │                                                │     (game_segments, title_history)
       │                                                └──► announce_game_change() (чат)
       │
       ├── stream.online ─────────────────────────────► eventsub_service
       │     (стрим начался)                              │
       │                                                ├──► RuntimeStreamCollector.start_session()
       │                                                └──► capture_runtime_sample()
       │
       ├── stream.offline ────────────────────────────► eventsub_service
       │                                                └──► RuntimeStreamCollector.finalize_session()
       │
       ├── channel.raid ──────────────────────────────► eventsub_service
       │                                                └──► maybe_send_raid_shoutout()
       │
       ├── channel.follow.v2 ─────────────────────────► eventsub_service
       │                                                └──► RuntimeStreamCollector.handle_follow()
       │
       └── channel.shoutout.create/receive ──────────► eventsub_service
                                                        (cooldown tracking)

RuntimeStreamCollector
  ├── sampling_loop()              каждые N секунд (STREAM_RUNTIME_SAMPLE_SECONDS)
  │    ├── fetch_live_stream()     Twitch API (viewers, title, game)
  │    ├── fetch_followers_count() Twitch API (total followers)
  │    └── _recalculate_metrics()  avg_viewers, max_viewers, hours_watched
  │                                viewer_buckets_10m (аналог TwitchTracker)
  │
  ├── active session              active_stream_session.json (in-memory + JSON)
  └── completed sessions          completed_stream_sessions.json (история)
```

---

## 6. Ключевые архитектурные решения

| Решение | Где реализовано |
|---|---|
| **Pipeline как CLI** | Все оркестраторы — `python -m pipeline.orchestrator.*`. Нет встроенного планировщика |
| **Safe-sync с Sheets** | `sync_games_safe()` / `sync_streams_safe()` — сохраняет ручные колонки H,J |
| **Sliding-window rate limiter** | `_SlidingWindowRateLimiter` в `ingest/igdb_api.py` (4 req/s для IGDB) |
| **Debounced sheets sync** | `RecommendationSheetsSyncScheduler` (15s debounce после `!рек`) |
| **Kill-switch** | `runtime.BOT_ENABLED` — блокирует все команды кроме `!старт` |
| **VOD matching** | `streams_transform.py` — по дате ±1 день + пересечение title |
| **Game segments** | `RuntimeStreamCollector` — сегменты игр внутри стрима с метриками |

---

## 7. Известные узкие места

```
Проблема                              Где                    План
──────────────────────────────────────────────────────────────────────────
Циркулярные зависимости               pipeline ↔ services    Выделить shared/core
RuntimeStreamCollector — God class    ~1000 строк            Разделить на sampler/storage/calculator
Нет абстракции БД (Repository)        Прямой SQLAlchemy      Репозитории в shared/
Конфиг — плоские глобальные переменные config/settings.py    pydantic-settings
Нет тестов                            Весь проект            После выделения shared/
Нет API для веба/телеграма            Нет                    FastAPI отдельным приложением
```
