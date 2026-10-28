# AGENTS.md

Краткая карта проекта для ИИ-агентов. Читай этот файл перед изменениями, затем
открывай профильный документ из раздела «Документация».

## 1. Что это за проект

`streamflow` — автоматизация Twitch-канала Mishgan:

- Twitch-бот на `TwitchIO`: команды чата, модерация, рекомендации, таймеры;
- ETL-пайплайн: Twitch / IGDB / HLTB / TwitchTracker → PostgreSQL → Google Sheets;
- сбор live-метрик стрима (Runtime Stream Collector) и EventSub-события;
- Telegram-бот: правка анонсов после стрима ссылкой на VOD;
- веб-приложение: `FastAPI` API (`backend/`) + React-фронтенд (`frontend/`).

Основная БД — **PostgreSQL** (`DATABASE_URL`, `postgresql+asyncpg://...`).
SQLite и `storage/streams.db` — legacy, не использовать для новой логики.

## 2. Стек и точки входа

| Часть | Точка входа | Технологии |
|---|---|---|
| Twitch-бот | `bot.py` | Python 3.14, TwitchIO 3, asyncio |
| HTTP API | `backend.main:app` | FastAPI, Pydantic, SQLAlchemy async |
| Миграции | `alembic/` | Alembic, asyncpg |
| ETL | `pipeline/orchestrator/*.py` | CLI-скрипты, SQLAlchemy async |
| Live-метрики | `runtime/collector.py` | EventSub, asyncio |
| Telegram | `telegram/service.py` | aiogram |
| Фронтенд | `frontend/src/main.tsx` | React 19, TypeScript, Vite, Tailwind 4 |
| Синхронизация Sheets | `pipeline/delivery/`, `services/sheets_service.py` | gspread |

Docker: `docker-compose.yml` поднимает `db` (PostgreSQL 16), `bot` и `backend`.
`backend` при старте выполняет `alembic upgrade head`.

## 3. Быстрый старт

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# заполнить .env по .env.example
docker compose up -d db

# миграции
.venv\Scripts\python.exe -m alembic upgrade head

# Twitch-бот
.venv\Scripts\python.exe bot.py

# API
.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8001
```

```powershell
# фронтенд
cd frontend
npm install
npm run dev
```

Проверки:

```powershell
.venv\Scripts\python.exe -m pytest tests -q
cd frontend; npm run lint; npm run typecheck; npm test
```

API: `http://127.0.0.1:8001/api/v1`, Swagger — `http://127.0.0.1:8001/docs`,
OpenAPI — `http://127.0.0.1:8001/openapi.json`. Фронтенд — `http://localhost:5173`.

## 4. Карта репозитория

```
bot.py                    запуск Twitch-бота
core/                     инициализация бота, загрузка команд
commands/                 обработчики чат-команд (по одному модулю на команду)
services/                 бизнес-логика, интеграции, авторизация
  authz_service.py        роли, capability, ограничения, resolve_actor
  chat_service.py         диспетчеризация/очереди сообщений
  twitch_service.py       Twitch Helix API, токены
  eventsub_service.py     EventSub-подписки
  recommendations_service.py
  gpt_service.py          Gemini → OpenRouter → g4f
database/                 SQLAlchemy-модели и сессии
  models.py               все ORM-модели (единый файл)
  db.py                   Base, engine, AsyncSessionLocal
runtime/                  live-метрики стрима
pipeline/
  ingest/                 клиенты Twitch, IGDB, HLTB, Sheets, TwitchTracker
  transform/              чистые функции нормализации
  load/                   запись в PostgreSQL
  delivery/               выгрузка в Google Sheets / legacy JSON
  orchestrator/           CLI-скрипты ETL
telegram/                 aiogram-бот и правка постов
backend/
  main.py, app.py         сборка FastAPI-приложения
  routers/                HTTP-эндпоинты
  schemas/                Pydantic-схемы
  repositories/           запросы к БД для API
  security/               cookie-сессии, CSRF, OAuth
frontend/src/             React-приложение
alembic/versions/         миграции (не редактировать применённые)
storage/                  локальные данные, кэш, логи, runtime-файлы
tests/                    pytest-тесты (backend, authz, telegram)
docs/                     профильная документация
```

## 5. Ключевые потоки

### Чат-команда

1. `core/registry.py` импортирует модули `commands/*` и вызывает `setup(bot)`.
2. `services.command_registry.register_command(...)` записывает метаданные
   (описание, алиасы, `access`) в реестр/БД.
3. Обработчик в `commands/*.py` проверяет кулдаун (`utils/cooldowns.py`),
   задержку (`utils/delays.py`) и права (`services/authz_service.py`).
4. Ответ отправляется через `ctx.send(...)` или `services/chat_sender.py`.

Новую команду добавляй отдельным модулем в `commands/`, регистрируй через
`register_command`, не забывай про `bot.add_command` и тесты.

### Права

- Роли: `owner` (100), `streamer` (80), `admin` (60), `editor` (40), `user` (20).
- Capability: `RECOMMEND`, `EDIT_TABLES`, `ADMIN_COMMANDS`,
  `MANAGE_EDITORS`, `MANAGE_STAFF`, `MANAGE_SERVICE_BAN`.
- Проверка: `resolve_actor(...)` → `Actor.can_command(Capability.X)` для команд;
  `Actor.can(...)` — для веб-записей (учитывает service ban).
- Owner задаётся bootstrap-переменными `OWNER_TWITCH_USER_ID` /
  `OWNER_TWITCH_LOGIN`, но роль хранится в `users.role`.
- Не дублируй проверки ролей вручную: используй `authz_service`.

### Данные

- Новые таблицы/поля — только через новую Alembic-миграцию.
- ORM-модели — в `database/models.py`; после изменения проверяй
  `alembic revision --autogenerate`.
- Для API используй `backend/repositories/` и `AsyncSessionLocal`, не создавай
  отдельные engine/сессии.
- Даты в БД и API — naive UTC ISO 8601; локальное время — на фронтенде.

### Веб-API и фронтенд

- API под `/api/v1`, ошибки в формате
  `{"detail": {"code": "...", "message": "..."}}`.
- Авторизация — Twitch OAuth + HttpOnly cookie `backend_session_id`.
- Для `POST/PATCH/DELETE` нужен `X-CSRF-Token` из cookie `backend_csrf_token`.
- OpenAPI-типы фронтенда генерируются в `frontend/src/api/schema.d.ts`
  командой `npm run gen:api`; не редактировать файл вручную.
- Фронтенд ходит через `/api` (Vite proxy) с `withCredentials: true`.
- UI-токены и палитра разделов — в `frontend/src/index.css`.

## 6. Чат-команды (актуальный набор)

| Команда | Назначение |
|---|---|
| `!игры [игра]`, `!игра` | статистика по игре |
| `!стримы [ДД.ММ.ГГ]`, `!стрим` | информация о стриме за дату |
| `!hltb [игра]` | время прохождения из HowLongToBeat |
| `!праздник [все/номер/поиск/дата]` | праздники |
| `!время` | длительность стрима и категорий |
| `!рек [игра]` | рекомендация/голос; `-` удалить свою, `- <игра>` удалить по названию, `-- <user> [игра]` админское удаление, `+ <игра>` добавить от стримера |
| `!фильм`, алиасы `!сериал !серия !кино !film !movie !начало !сезон !lost !лост` | текущий фильм; `+`/`-`/`time` — управление для админов |
| `!r` (ответом на сообщение) | перевод текста из неправильной раскладки |
| `!инфо [тема]` | справка по стримеру/компьютеру/девайсам |
| `!команды [команда]`, `!команда`, `!помощь`, `!help` | справка по командам |
| `!таймер [10м/1ч] [текст]`, `!таймер`, `!таймер стоп`, `!таймер возврат [стоп]` | глобальный таймер; статус доступен всем, управление — модераторам/staff |
| `!gpt <вопрос>` | вопрос LLM, требуется `ADMIN_COMMANDS` |
| `!отбой`, `!старт` | включить/выключить бота, требуется `ADMIN_COMMANDS` |

Подробности и ограничения — `docs/CHAT_COMMANDS.md`.

## 7. Внешние интеграции

- **Twitch Helix / EventSub / IRC** — `services/twitch_service.py`,
  `services/eventsub_service.py`, `pipeline/ingest/twitch_api.py`.
- **IGDB** — `pipeline/ingest/igdb_api.py`, `services/igdb_service.py`
  (`IGDB_CLIENT_ID`/`IGDB_CLIENT_SECRET`, fallback на `CLIENT_ID`/`CLIENT_SECRET`).
- **HowLongToBeat** — `pipeline/ingest/hltb_client.py`, `services/hltb_service.py`.
- **Google Sheets** — `services/sheets_service.py`, `pipeline/delivery/`,
  `pipeline/ingest/google_sheets_reader.py`; сервисный аккаунт
  `config/credentials.json`.
- **LLM** — `services/gpt_service.py`: Gemini (`GEMINI_API_KEY`,
  `GEMINI_MODEL`, по умолчанию `gemini-2.5-flash`) → OpenRouter
  (`OPENROUTER_API_KEY`) → `g4f`.
- **Праздники** — `services/holiday_service.py` читает PostgreSQL
  (`calendar_days`, `holidays`); разовое заполнение —
  `database/sync_holidays.py` из `storage/holidays.json`.
- **Telegram** — `telegram/` (`TELEGRAM_ENABLED`, `TELEGRAM_BOT_TOKEN`,
  `TELEGRAM_CHANNEL_ID`).

## 8. Переменные окружения (основное)

Полный список — `.env.example` и `config/settings.py`.

- Twitch-бот: `TWITCH_TOKEN`, `TWITCH_NICK`, `TWITCH_CHANNEL`/`TWITCH_CHANNELS`,
  `TWITCH_BOT_BADGE_CHANNELS`.
- Twitch API: `CLIENT_ID`, `CLIENT_SECRET`, `BOT_ID`.
- БД: `DATABASE_URL`.
- Владелец: `OWNER_TWITCH_USER_ID`, `OWNER_TWITCH_LOGIN`.
- Рекомендации: `RECOMMENDATIONS_LIMIT`, `RECOMMENDATIONS_STREAMER_LOGIN`.
- Runtime: `STREAM_RUNTIME_SAMPLE_SECONDS`.
- Веб: `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`, `TWITCH_REDIRECT_URI`,
  `TWITCH_SCOPE`, `TWITCH_STREAMER_SCOPE`, `BACKEND_*`,
  `TOKEN_ENCRYPTION_KEY`.
- Telegram: `TELEGRAM_ENABLED`, `TELEGRAM_BOT_TOKEN`,
  `TELEGRAM_CHANNEL_ID` (числовой id `-100…`), `TELEGRAM_VOD_*`.
- Google Sheets: `GAMES_SHEET_URL` + `config/credentials.json`.

Секреты не коммитить. `.env`, `config/credentials.json` и токены — локальные.

## 9. Правила для ИИ-агента

1. Сначала прочитай этот файл и профильный документ в `docs/`; не сканируй весь
   репозиторий без необходимости.
2. Соблюдай границы модулей: команды — `commands/`, бизнес-логика — `services/`,
   запросы API — `backend/repositories/`, ETL — `pipeline/`.
3. Не редактируй уже применённые миграции; создавай новую.
4. Не редактируй `frontend/src/api/schema.d.ts` и `frontend/openapi.json`
   вручную — перегенерируй.
5. Не меняй `storage/runtime/`, `storage/logs/`, `storage/cache/` без задачи.
6. После изменений запускай релевантные проверки: `pytest`, `npm run lint`,
   `npm run typecheck`, `npm test`.
7. Не коммить, не пушить и не переписывать историю без явной просьбы.
8. Не удаляй чужие незакоммиченные изменения: рабочее дерево может быть грязным.

## 10. Документация

- `README.md` — обзор, запуск, конфигурация.
- `docs/ARCHITECTURE.md` — архитектура, ETL, runtime, Telegram, backend.
- `docs/CHAT_COMMANDS.md` — команды чата и права.
- `docs/DATABASE.md` — таблицы, связи, миграции.
- `docs/DATA_SOURCES.md` — внешние источники и пайплайны.
- `docs/API.md` — HTTP API, auth, CSRF, эндпоинты.
- `docs/FRONTEND.md` — структура фронтенда, роуты, дизайн-токены.
- `docs/TELEGRAM.md` — Telegram-анонсы и правка VOD.
- `docs/plans/` — исторические планы и аналитика (не актуальная спека).
