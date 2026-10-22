# Анализ и план: веб-бэкенд на FastAPI

Дата: 2026-10-09
Статус: Шаги 0–5 и 7 реализованы (read + write + тесты); Шаг 6 (OAuth) — заготовки/заглушки

Цель: спроектировать backend веб-сервиса проекта `streamflow` на FastAPI,
который со временем заменит Google Sheets как UI. Google Sheets пока
остаётся рабочим, но новый сервис должен быть **независим** от кода
`pipeline/delivery` (логика дублируется, а не переиспользуется).

---

## 1. Зафиксированные решения

| # | Вопрос | Решение |
|---|--------|---------|
| 1 | Чтение/запись | Реализуем и чтение, и запись сразу |
| 2 | Авторизация | Twitch OAuth. Реализацию пользователь делает лично; от нас — только предложения и заготовки |
| 3 | Google Sheets | Пока оставляем. Новый сервис **не зависит** от `pipeline/delivery`; запросы дублируются в web-слой |
| 4 | Стримеров | Один, как сейчас: `SHEETS_STREAMER_ID = 45` |
| 5 | Размещение | Отдельный пакет в этом репозитории, общий PostgreSQL |
| 6 | Фронтенд | Планируется; технологии ещё не выбраны → API проектируем версионируемым и стабильным |
| 7 | Файл анализа | `docs/WEB_BACKEND_FASTAPI_ANALYSIS.md` |

---

## 2. Текущее состояние (проверено по коду)

### 2.1. Что уже есть

- **БД:** PostgreSQL, SQLAlchemy 2.0 **async** + `asyncpg` + Alembic.
  - `database/db.py:21-24` — `async_engine`, `AsyncSessionLocal`.
  - `database/db.py:28-29` — legacy sync-движок (для старого кода).
  - Alembic: миграции `0001`–`0010` в `alembic/versions/`.
- **Модели** (`database/models.py`): `games`, `streams`, `stream_titles`,
  `stream_games`, `stream_recordings`, `users`, `user_profiles`, `genres`,
  `platforms`, `game_metadata_igdb`, `game_metadata_hltb`, `game_stats`,
  `game_aliases`, `game_recommendations`, `streamer_games`,
  `streamers_on_stream`, а также домены clips/duels/telegram/rewards/analytics.
- **Заготовки под веб** (кодом не используются):
  - `web_sessions` (`models.py:317-324`);
  - `twitch_authorizations` (`models.py:304-314`).
- **Доменные сервисы** (async, `services/`):
  - `games_service.py` — поиск/ранжирование игр, `build_game_response`;
  - `streams_service.py` — выборка стримов по дате;
  - `recommendations_service.py` — логика `!рек` (add/delete, лимит, дубликаты,
    banned, статусы upcoming/released/streamed).

### 2.2. Чего нет

- FastAPI/uvicorn/pydantic в `requirements.txt` — отсутствуют полностью
  (проверено поиском по коду: совпадений нет).
- `database/schemas.py` (Pydantic) — отсутствует.
- ASGI-приложения, роутеров, `static/`, тестового `TestClient` — нет.
- `get_session()`-зависимости для FastAPI — нет.
- pytest — нет; тесты на stdlib `unittest`.

### 2.3. Откуда берётся логика представлений

Четыре «листа» — это четыре разных источника данных:

| Лист | Источник | Где сейчас реализовано |
|------|----------|------------------------|
| ИГРЫ | `games ⋈ stream_games ⋈ game_stats` + флаги `streamer_games` | `pipeline/delivery/sheets_games.py`, `services/games_service.py:97-142` |
| СТРИМЫ | `streams ⋈ stream_games ⋈ stream_recordings` + участники | `pipeline/delivery/sheets_streams.py` |
| РЕЛИЗЫ | `game_recommendations ⋈ game_metadata_igdb`, `release_date > now OR NULL` | `pipeline/delivery/sheets_releases.py:298-347` |
| СОВЕТЫ | `game_recommendations ⋈ game_metadata_igdb`, `release_date <= now` | `pipeline/delivery/sheets_recommendations.py:168-211` |

Важно: **«РЕЛИЗЫ» и «СОВЕТЫ» — не отдельные таблицы**, а производные
представления над `game_recommendations` + `game_metadata_igdb.release_date`.
Статус игры вычисляется на лету
(`pipeline/transform/recommendations_transform.py`,
`services/recommendations_service.py:112-146`).

### 2.4. Ручные пометки

- ИГРЫ: `streamer_games.liked` (колонка H), `streamer_games.completed` (J),
  обратная синхронизация из листа — `sheets_games.py:102`
  (`_sync_game_manual_fields_from_sheet`).
- РЕЛИЗЫ: `streamer_games.interested` (колонка F) —
  `sheets_releases.py:267-296`.
- Привязка к `config/settings.py:75` → `SHEETS_STREAMER_ID = 45`.
- В листах идентичность строки определяется естественным ключом
  (название игры / дата+заголовок стрима), **ID-колонки нет**.

---

## 3. Целевая архитектура

```
┌─────────────────────────────────────────────────────────────┐
│  backend/  (FastAPI, отдельный пакет в репозитории)             │
│                                                             │
│  backend/main.py          ASGI app, uvicorn entrypoint          │
│  backend/app.py           create_app(), CORS, exception handlers│
│  backend/deps.py          get_session(), current_user, roles     │
│  backend/config.py        настройки веб-слоя (pydantic-settings) │
│  backend/schemas/         Pydantic DTO (in/out)                  │
│  backend/repositories/    свой query-слой (НЕ импортирует       │
│                       pipeline.delivery)                     │
│  backend/routers/         games, streams, releases,              │
│                       recommendations, auth, health          │
│  backend/security/        Twitch OAuth + сессии (заготовки)      │
└─────────────────────────────────────────────────────────────┘
          │
          ▼  AsyncSessionLocal (database/db.py)
    PostgreSQL (общий с ботом)
```

### Ключевой принцип

Web-слой:
- **использует** `database/models.py` и `database/db.py` (общая схема и движок);
- **дублирует** запросы представлений ИГРЫ/СТРИМЫ/РЕЛИЗЫ/СОВЕТЫ вместо
  импорта `pipeline/delivery/*`;
- **не импортирует** `gspread`, `oauth2client`, Google-клиент;
- **минимизирует** импорт тяжёлых модулей (`g4f`, `twitchio`, IGDB-клиент).

Trade-off (осознанно принимаем): дублирование запросов даёт независимость,
но создаёт риск расхождения с Sheets. Митигация — зафиксировать DTO и
покрыть выборки тестами; при отказе от Sheets старый код удаляется целиком
(см. Шаг 10).

---

## 4. Варианты имени пакета

| Вариант | Плюсы | Минусы |
|---------|-------|--------|
| `backend/` | коротко, отражает «веб-сервис», не путается с `bot.py` | слишком общее, если будет и фронт в репо |
| `webapi/` | явно про API | менее привычное имя |
| `backend/` | явно бэкенд | конфликтует по смыслу с ETL и ботом |
| `server/` | нейтрально | не отражает HTTP/веб |
| `app/` | коротко | путается с `backend/app.py`, слишком общее |
| `webapp/` | читаемо | длинно |

**Рекомендация:** `backend/` с точкой входа `backend/main.py` (`backend.main:app`).
Имя короткое, согласуется со стилем репозитория (плоские верхнеуровневые
пакеты: `commands/`, `services/`, `pipeline/`, `telegram/`). Фронтенд позже
можно вынести в отдельный `frontend/`.

---

## 5. Проектирование API

### 5.1. Общие принципы

- Префикс версии: `/api/v1/...` — чтобы фронт не ломался при изменениях.
- Пагинация: `limit`/`offset` (как в существующих сервисах) или cursor для
  больших списков; ответ-обёртка `{items, total, limit, offset}`.
- Ошибки: единый JSON `{detail, code}`; 404/403/409/422 осмысленно.
- Схемы: Pydantic v2, `model_config = ConfigDict(from_attributes=True)`.
- Все обращения к БД — async + eager-load (`selectinload`) отношений.
- Даты — ISO 8601 UTC (см. риск 8.5).

### 5.2. Read-эндпоинты

| Метод | Путь | Назначение |
|-------|------|------------|
| GET | `/api/v1/games` | список игр (как лист ИГРЫ): rank, streams_count, hours, last_stream, hltb, steam, liked, completed, tags |
| GET | `/api/v1/games/{id}` | одна игра + метаданные |
| GET | `/api/v1/streams` | список стримов: дата, длительность, игры, VOD, участники, теги; фильтры `date`, `from`, `to` |
| GET | `/api/v1/streams/{id}` | один стрим + игры/участники/записи |
| GET | `/api/v1/releases` | будущие/без даты рекомендации (лист РЕЛИЗЫ) |
| GET | `/api/v1/recommendations` | вышедшие рекомендации с числом голосов (лист СОВЕТЫ) |
| GET | `/api/v1/games/search?q=` | серверный поиск (переиспользовать логику `find_game_lookup`) |
| GET | `/api/v1/meta/genres`, `/api/v1/meta/platforms` | справочники для фильтров фронта |
| GET | `/api/v1/health` | liveness/readiness, проверка БД |

### 5.3. Write-эндпоинты (сразу)

| Метод | Путь | Назначение | Аналог в Sheets |
|-------|------|------------|-----------------|
| PATCH | `/api/v1/games/{id}/streamer-state` | `{liked: bool, completed: bool}` | колонки H/J листа ИГРЫ |
| PATCH | `/api/v1/releases/{id}/interested` | `{interested: bool}` | колонка F листа РЕЛИЗЫ |
| POST | `/api/v1/recommendations` | добавить рекомендацию `{query}` | `!рек <игра>` |
| DELETE | `/api/v1/recommendations/{game_id}` | удалить свою рекомендацию | `!рек - <игра>` |

Write-операции для рекомендаций **переиспользуют** доменную логику
`services/recommendations_service.py` и `pipeline/load/load_recommendations.py`
(это не Sheets-зависимый код). Read-выборки представлений — дублируются.

### 5.4. Авторизация (предложения; реализацию делает пользователь)

Заготовки уже есть в схеме: `web_sessions`, `twitch_authorizations`.

Предлагаемый флоу (Twitch OAuth Authorization Code):
1. `GET /api/v1/auth/login` → редирект на `https://id.twitch.tv/oauth2/authorize`
   со `scope` (минимум `user:read:email`, при необходимости `openid`).
2. `GET /api/v1/auth/callback?code=...` → обмен кода на токены на
   `https://id.twitch.tv/oauth2/token`; получить `GET /helix/users` для
   `twitch_user_id`/`login`.
3. Сопоставить `twitch_user_id` с `users.twitch_user_id`; создать/найти `User`.
4. Создать `web_sessions` (UUID PK) с TTL; положить в HttpOnly+Secure+SameSite
   cookie. Токены (при необходимости) — в `twitch_authorizations`.
5. Роли: `users.is_admin` / `is_streamer` / список `ADMINS`
   (`config/settings.py:65`). Write-операции разрешать стримеру и админам.

Что предусмотреть на нашей стороне (заготовки, без «глубокой» реализации):
- `backend/deps.py`: `get_current_user`, `require_streamer_or_admin`;
- незаполненные хендлеры `auth` с TODO;
- модель сессии и cookie-настройки в `backend/config.py`.

Безопасность, о которой стоит помнить пользователю: CSRF для cookie-сессий,
`state`-параметр OAuth, ротация refresh-токенов, срок жизни `web_sessions`,
хранение секретов только в `.env`.

---

## 6. Пошаговый план реализации

### Шаг 0. Зависимости и каркас
- Добавить в `requirements.txt`: `fastapi`, `uvicorn[standard]`, `pydantic`,
  `pydantic-settings`. Проверить конфликты с `g4f`/`openai`/`twitchio`.
- Создать `backend/` с `main.py`, `app.py`, `config.py`, `deps.py`.
- `get_session()` как async-генератор над `AsyncSessionLocal`.
- CORS (origin фронта), `/api/v1/health`.

### Шаг 1. Pydantic-схемы
- `backend/schemas/common.py` (пагинация, ошибки), `game.py`, `stream.py`,
  `release.py`, `recommendation.py`, `auth.py`.

### Шаг 2. Read-слой (дублирование из delivery)
- `backend/repositories/games.py` — портировать `_build_games_dataset`
  (`sheets_games.py`) и ранжирование (`games_service.py:97-142`).
- `backend/repositories/streams.py` — портировать выборку + теги/участники/VOD
  (`sheets_streams.py`).
- `backend/repositories/releases.py` — портировать запрос `release_date > now OR NULL`
  (`sheets_releases.py:298-347`).
- `backend/repositories/recommendations.py` — портировать `release_date <= now`
  + `votes_count` (`sheets_recommendations.py:168-211`).
- Общие хелперы (теги платформ/жанров, recommenders, дельта релиза) — в
  `backend/repositories/_shared.py` (копии из `sheets_utils.py`, без gspread).

### Шаг 3. Read-роутеры
- `games`, `streams`, `releases`, `recommendations`, `meta`, `health`.
- Пагинация, фильтры, сортировки, соответствующие листам.

### Шаг 4. Write: ручные пометки
- `PATCH /games/{id}/streamer-state` и `PATCH /releases/{id}/interested`:
  upsert в `streamer_games` для `SHEETS_STREAMER_ID = 45`,
  семантика как в `sheets_games.py:102` и `sheets_releases.py:267-296`.
- Задел на будущее многопользовательское редактирование (параметр `streamer_id`
  пока фиксирован).

### Шаг 5. Write: рекомендации
- `POST`/`DELETE` поверх `services/recommendations_service.py` (лимит, дубликаты,
  banned, статусы, IGDB-обогащение уже реализованы).
- Не тянуть Google/Sheets в этот путь.

### Шаг 6. Авторизация (заготовки)
- `backend/security/twitch_oauth.py`, `backend/security/sessions.py` с TODO.
- `get_current_user` / `require_streamer_or_admin` в `backend/deps.py`.
- Cookie-конфиг в `backend/config.py`; отдельно решить CSRF-защиту.
- Реализацию OAuth-обмена пользователь дописывает сам.

### Шаг 7. Тесты
- `tests/test_web_*.py` на stdlib `unittest` + `fastapi.testclient.TestClient`
  (Starlette TestClient; нужен `httpx`, если ещё нет — он есть транзитивно).
- Отдельная тест-БД (схема/контейнер) — НЕ прод.
- Покрыть: схемы, выборки (сравнение с ожидаемыми DataFrame-эквивалентами),
  write-операции, права доступа.

### Шаг 8. Упаковка и деплой
- Точка входа: `uvicorn backend.main:app --host ... --port ...`.
- `docker-compose.yml`: добавить сервис `backend` (общий `db`), порт (напр. 8001,
  чтобы не мешать другим), healthcheck.
- Обновить `.env.example`: веб-переменные (OAuth, cookie, CORS).
- Обновить `docs/ARCHITECTURE.md` и `README.md`.

### Шаг 9. Наблюдаемость
- Structured logging, корреляция запросов; `/health` c проверкой БД.
- (Опционально) метрики запросов.

### Шаг 10. Вывод Sheets из эксплуатации (после стабилизации)
- Отключить `sync_sheets` и обратную синхронизацию ручных колонок.
- Удалить `pipeline/delivery/*` и Google-зависимости из `requirements.txt`.
- Только тогда дублирование перестаёт быть риском.

---

## 7. Что дублировать, а что переиспользовать

| Логика | Решение |
|--------|---------|
| Выборки ИГРЫ/СТРИМЫ/РЕЛИЗЫ/СОВЕТЫ | **Дублировать** из `pipeline/delivery` в `backend/repositories` |
| Форматтеры (tags, recommenders, delta) | **Копировать** из `sheets_utils.py` без `gspread` |
| `services/recommendations_service.py` | **Переиспользовать** (доменная логика, не Sheets) |
| `services/games_service.py` (поиск) | Частично переиспользовать/обернуть |
| `database/models.py`, `database/db.py` | **Переиспользовать** (общая схема/движок) |
| `pipeline/delivery/*`, `gspread`, `oauth2client` | **Не импортировать** |
| `pipeline/ingest/igdb_api.py` | Переиспользовать только там, где нужно (add recommendation) |

---

## 8. Потенциальные проблемы и риски

1. **Расхождение дублированной логики с Sheets.** Пока Sheets жив, запросы в
   двух местах могут разойтись. Митигация: тесты + фиксация DTO; в перспективе
   удаление delivery.
2. **Тяжёлые импорты и циклические зависимости.** `services/*` тянет IGDB,
   `g4f`, `twitchio`, Google. Импорт `pipeline` в web-слое замедлит старт и
   усложнит зависимости. Митигация: изолировать read-слой, отложенные импорты.
3. **Async lazy-load.** Сериализация отношений без eager-load → `MissingGreenlet`.
   Обязательны `selectinload`/`joinedload`.
4. **Pydantic v2 и конфликты зависимостей.** Сейчас pydantic нет; FastAPI
   подтянет v2. Проверить совместимость с `g4f`/`openai`/`twitchio`/`SQLAlchemy`.
5. **Таймзоны.** Смешаны `datetime.utcnow()` (naive) и
   `datetime.now(timezone.utc)` (`recommendations_service.py:131`). Сравнения
   дат релиза и дельта «N д.» могут отличаться от Sheets. Зафиксировать
   единое соглашение (UTC, timezone-aware) в web-слое.
6. **Привязка к `SHEETS_STREAMER_ID=45`.** Для одного стримера ок; заложить
   параметр для будущего мультиюзера.
7. **Тестовая БД.** Async Postgres без стратегии изоляции → риск писать в прод.
8. **Авторизация с нуля.** Нет `python-jose`/`passlib`; `web_sessions`/
   `twitch_authorizations` пустые. CSRF/state/cookie — зона ручной реализации.
9. **Docker.** `docker-compose.yml` содержит только `bot` + `db`; Dockerfile
   `CMD` — бот. Нужен отдельный сервис/overlay для web.
10. **Публичные данные и приватность.** `user_profiles` (логины/аватары),
    `chat_messages` не должны утекать через API без необходимости.
11. **Идентичность строк без ID.** В Sheets ключ — название/дата+заголовок;
    в API нужно использовать `id` (стабильный), а дубликаты имён учесть.
12. **`refresh_recommendation_lifecycle` — заглушка** (`recommendations_service.py:445`).
    Статусы считаются на лету; не полагаться на «обновлённые» статусы в БД.

---

## 9. Открытые вопросы

1. Выбрать имя пакета (рекомендация — `backend/`).
2. Порт веб-сервиса и origin фронта для CORS.
3. Формат пагинации: `limit/offset` или cursor.
4. Нужен ли `GET /stats`/аналитика в v1 или позже.
5. Целевая версия Python для образа (в `.venv` замечены 3.13/3.14; образ в
   Dockerfile — 3.11). Зафиксировать совместимость FastAPI/uvicorn.

---

## 10. Состояние реализации (обновлено)

> Пакет назван `backend/` (изначально предлагался `web/`). Соответственно
> переименованы: класс настроек `BackendSettings`, фабрика
> `get_backend_settings()`, префикс переменных окружения `BACKEND_*`.
> Таблицы/модели БД `web_sessions` и `WebSession` не переименовывались.

Реализовано в пакете `backend/` (Шаги 0–7):

- **Каркас:** `backend/main.py` (`backend.main:app`), `backend/app.py`
  (`create_app()`, CORS, обработчики ошибок `{detail:{code,message}}`),
  `backend/config.py` (`BackendSettings` на `pydantic-settings`), `backend/deps.py`
  (`get_session`, `get_current_user`, `require_streamer_or_admin`, `require_admin`).
- **Схемы:** `backend/schemas/{common,game,stream,release,recommendation,auth}.py`.
- **Read-слой (не зависит от `pipeline.delivery`):**
  `backend/repositories/{_shared,games,streams,releases,recommendations}.py`.
- **Роутеры:** `games` (list/get/search + PATCH `streamer-state`),
  `streams` (list с фильтрами `date`/`from`/`to`, get), `releases` (list +
  PATCH `interested`), `recommendations` (list + POST/DELETE через
  `services.recommendations_service`), `meta` (genres/platforms), `health`,
  `auth` (`me`, `login`, `callback`, `logout` — полный OAuth, см. ниже).
- **Тесты:** `tests/test_backend_schemas.py`, `tests/test_backend_repositories_shared.py`,
  `tests/test_backend_api.py` (stdlib `unittest` + `TestClient`; БД не требуется —
  репозитории и сессия подменяются).

### Авторизация (Шаг 6, реализовано)

- **Twitch OAuth:**
  - `GET /api/v1/auth/login` создаёт одноразовый `state`, сохраняет его в HttpOnly
    cookie и перенаправляет пользователя в Twitch (`307`); если OAuth не настроен —
    `503 oauth_not_configured`.
  - `GET /api/v1/auth/callback` проверяет `state`, обменивает authorization code на
    токены и получает профиль через `/helix/users`.
  - Пользователь и актуальный профиль сохраняются в `users` и `user_profiles`;
    OAuth-токены — в `twitch_authorizations`.
  - Роли `is_admin`/`is_streamer` назначаются по `ADMINS` и
    `RECOMMENDATIONS_STREAMER_LOGIN`/`BACKEND_STREAMER_ID`.
  - `POST /api/v1/auth/logout` (`204`) удаляет серверную web-сессию и cookies.
- **Web-сессии и CSRF:**
  - Сессии хранятся в `web_sessions`, идентификатор — UUID в HttpOnly cookie.
  - Истёкшие сессии отклоняются при каждом обращении.
  - Для небезопасных методов требуется совпадение cookie `backend_csrf_token` и
    заголовка `X-CSRF-Token`.
  - Cookie сессии — `SameSite=Lax`; в production включить `BACKEND_COOKIE_SECURE=true`.
- **Ротация Twitch-токенов:** `backend/security/twitch_tokens.py`
  (`get_twitch_access_token(session, user_id)`) блокирует запись авторизации
  (`with_for_update`), проверяет срок и при необходимости делает refresh; новые
  токены и срок пишутся в `twitch_authorizations`. Ротация начинается за
  `TWITCH_TOKEN_REFRESH_SKEW_SECONDS` (по умолчанию 300 с) до истечения.
- **Очистка сессий:** фоновая задача в `lifespan` удаляет `web_sessions` с
  `expires_at <= now()` сразу после старта и далее каждые
  `BACKEND_SESSION_CLEANUP_INTERVAL_SECONDS` (по умолчанию 3600 с). Временная
  ошибка БД не останавливает API — следующая итерация повторяет попытку.
- **Настройки OAuth** (`.env`, URI должен совпадать с Twitch Application):

  ```
  TWITCH_CLIENT_ID=...
  TWITCH_CLIENT_SECRET=...
  TWITCH_REDIRECT_URI=http://127.0.0.1:8001/api/v1/auth/callback
  TWITCH_SCOPE=user:read:email
  ```

  Остальные настройки cookie, CSRF, TTL и ротации — в `.env.example`.

### Деплой (Шаг 8, реализовано)

- `docker-compose.yml`: сервис `backend` (общий образ с ботом, порт `8001`,
  healthcheck на `/api/v1/health`, старт `alembic upgrade head && uvicorn
  backend.main:app --host 0.0.0.0 --port 8001`).
- `README.md` и `docs/ARCHITECTURE.md` обновлены (описание сервиса, запуск).
- `.env.example`: добавлены `BACKEND_FRONTEND_URL` и прочие web-настройки.

### Ещё не сделано

- **Наблюдаемость (Шаг 9):** structured logging + request-id (health уже проверяет БД).
- **Вывод Sheets из эксплуатации (Шаг 10).**
- **Тесты:** покрытие OAuth/CSRF/сессий/ротации/cleanup (сейчас auth покрыт лишь
  маршрутами и проверкой `state`).

### Фронтенд (отдельная работа)

Фронтенд разрабатывается **отдельно** (в WebStorm), не в этом репозитории.

- Интеграционное руководство: [WEB_API.md](WEB_API.md) — CORS/cookie, OAuth-флоу,
  CSRF, формат ответов, полный список эндпоинтов и примеры на `fetch`.
- После успешного входа `/auth/callback` редиректит на `BACKEND_FRONTEND_URL`
  (`?login=success`), если настройка задана; иначе возвращает JSON.
- Редактирование (`PATCH /games/{id}/streamer-state`,
  `PATCH /releases/{id}/interested`, `POST/DELETE /recommendations`) требует входа
  и заголовка `X-CSRF-Token`.
- Локально: `BACKEND_CORS_ORIGINS` = origin dev-сервера, `BACKEND_COOKIE_SECURE=false`;
  на домене — `https`, `BACKEND_COOKIE_SECURE=true`,
  `TWITCH_REDIRECT_URI=https://<домен>/api/v1/auth/callback`.

### Как запустить

```
.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8001
# документация: http://127.0.0.1:8001/docs
```

### Как тестировать

```
.venv\Scripts\python.exe -m unittest discover -s tests -t .
```
