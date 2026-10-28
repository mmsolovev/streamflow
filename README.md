# streamflow

Twitch-бот для стримерского чата, локальной автоматизации, сбора статистики по стримам и веб-приложения.

Проект совмещает пять частей:
- чат-бота на `TwitchIO` с командами для пользователей чата Twitch;
- локальный пайплайн сбора и хранения статистики по стримам и играм;
- табличный UI в `Google Sheets`, где удобно смотреть, дополнять и править данные;
- веб-бэкенд на `FastAPI` ([backend/](backend)) с авторизацией через Twitch OAuth;
- React-фронтенд ([frontend/](frontend)) — статистика, рекомендации, HLTB и админка.

## Что умеет

- отвечает на чат-команды `!команды`, `!праздник`, `!hltb`, `!инфо`, `!игры`, `!стримы`, `!r`, `!рек`, `!фильм`, `!время`;
- поддерживает команды с ограниченным доступом: `!таймер`, `!отбой`, `!старт`;
- умеет отвечать через LLM для разрешённых пользователей `!gpt`;
- автоматически делает `shoutout` при рейде с заданными условиями;
- собирает и хранит статистику стримов, игр и рекомендаций в `PostgreSQL`;
- выдает и принимает информацию о стримах, играх и рекомендациях по запросу в чате Twitch;
- синхронизирует данные в `Google Sheets`, где таблица используется как UI для просмотра и ручных пометок;
- собирает live-метрики стримов (Runtime Stream Collector);
- отдаёт данные по HTTP API и показывает их в веб-интерфейсе ([backend/](backend), [frontend/](frontend));
- после окончания стрима сам правит Telegram-анонс, подставляя ссылку на запись (VOD).

## Команды чата

Подробная инструкция для зрителей и модераторов — [docs/CHAT_COMMANDS.md](docs/CHAT_COMMANDS.md).

Кратко:
- `!команды` или `!команды <имя>`: список команд или справка по конкретной команде;
- `!время`: продолжительность стрима и отдельных категорий;
- `!праздник`: случайный праздник, список на сегодня, поиск по дате или названию;
- `!hltb <игра>`: примерное время прохождения игры;
- `!инфо <тема>`: локальная справка по стримеру, компьютеру и девайсам;
- `!игры <название>`: статистика по игре и ссылка на общую таблицу;
- `!стримы <дата>`: информация о стриме за дату и ссылка на общую таблицу;
- `!рек <название>`: предложить игру для стрима или проголосовать за уже предложенную;
- `!фильм`: текущий фильм; `+`/`-`/`time` — управление для админов;
- `!r`: перевод текста из неправильной раскладки при ответе через `Reply`;
- `!таймер ...`, `!gpt ...`, `!отбой`, `!старт`: команды с ограничением по роли.

## Архитектура

Подробно архитектура проекта описана в [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
Тематические документы: [команды чата](docs/CHAT_COMMANDS.md),
[база данных](docs/DATABASE.md), [источники данных](docs/DATA_SOURCES.md),
[HTTP API](docs/API.md), [фронтенд](docs/FRONTEND.md),
[Telegram](docs/TELEGRAM.md).

Центральная часть проекта — ETL-пайплайн, который отвечает за сбор, обработку и доставку данных. Он состоит из четырех слоев, работа которых координируется CLI-скриптами.

```
[Внешние источники]
 (Twitch API, IGDB)
         |
         v
+------------------+
|      INGEST      |  Сбор сырых данных в /storage/raw_data/
+------------------+
         |
         v
+------------------+
|    TRANSFORM     |  Очистка, структурирование, обогащение (GPT)
+------------------+
         |
         v
+------------------+
|       LOAD       |  Загрузка трансформированных данных в PostgreSQL
+------------------+
         |
         v
   [PostgreSQL]
         |
         v
+------------------+
|     DELIVERY     |  Синхронизация с Google Sheets
+------------------+
         |
         v
 [Google Sheets]
```

Помимо ETL, в проекте есть потребители данных из `PostgreSQL`: Twitch-бот,
EventSub/`runtime`-сборщик live-метрик, веб-бэкенд [backend/](backend)
(`FastAPI`) и React-фронтенд [frontend/](frontend).

### 1. Ingest (Сбор)
- **Что делает:** Собирает "сырые" данные из внешних источников.
- **Источники:** Twitch API (информация о стримах, играх), EventSub (live-метрики), IGDB (данные о релизах).
- **Результат:** JSON-файлы, сохраненные в директории `storage/raw_data/`. Этот слой не изменяет данные, только сохраняет их как есть.

### 2. Transform (Преобразование)
- **Что делает:** Приводит разнородные данные к единой структуре, очищает и обогащает их.
- **Процессы:**
    - Парсинг JSON-файлов из `Ingest`-слоя.
    - Валидация и очистка данных (удаление дубликатов, приведение типов).
    - Обогащение через внешние сервисы, например, получение описаний игр с помощью `g4f` (GPT).
- **Результат:** Готовые к загрузке Python-объекты (модели данных).

### 3. Load (Загрузка)
- **Что делает:** Загружает преобразованные данные в хранилище.
- **Хранилище:** База данных `PostgreSQL`.
- **Процесс:** Скрипты этого слоя принимают Python-объекты от `Transform` и, используя асинхронный `SQLAlchemy` + `asyncpg`, сохраняют их в соответствующие таблицы. Обеспечивается целостность данных и управление связями (например, между стримами и играми). Миграции схемы управляются через `Alembic`.

### 4. Delivery (Доставка)
- **Что делает:** Доставляет финальные данные конечным пользователям или системам.
- **Системы:**
    - **Google Sheets:** Основной UI для стримера. Данные из `PostgreSQL` выгружаются в таблицы, позволяя удобно просматривать статистику и делать ручные пометки. Реализована двусторонняя синхронизация для колонок, которые можно редактировать вручную.
    - **Twitch-бот:** Команды бота (`!игры`, `!стримы`) запрашивают данные напрямую из `PostgreSQL` для отображения в чате.

### Orchestration (Оркестрация)
- **Что делает:** Запускает и координирует работу всех слоев.
- **Реализация:** Набор CLI-скриптов в директории `pipeline/orchestrator/`. Каждый скрипт отвечает за определенную цепочку действий, например, `import_igdb_releases.py` выполняет полный цикл от сбора данных из IGDB до их загрузки в базу.
- **Запуск:** Осуществляется вручную стримером или по расписанию.

## CLI-оркестраторы

Для управления ETL-пайплайном используются следующие CLI-скрипты:
- `sync_sheets.py`: Синхронизирует данные с Google Sheets.
- `parse_games_json.py`: Парсит JSON-файлы с информацией об играх.
- `import_json_to_db.py`: Импортирует JSON-данные в базу данных.
- `parse_streams_json.py`: Парсит JSON-файлы с информацией о стримах.
- `import_igdb_releases.py`: Импортирует информацию о релизах игр из IGDB.
- `enrich_descriptions_with_gpt.py`: Обогащает описания с помощью GPT.

## Google Sheets как UI

Проект не просто выгружает данные из бд в таблицу, а использует `Google Sheets` как рабочий интерфейс:
- лист `ИГРЫ` показывает список игр, количество стримов, времени, вручную можно отметить оценку и статус прохождения;
- лист `СТРИМЫ` показывает дату, длительность, название, игры, ссылку на запись и участников;
- лист `РЕЛИЗЫ` показывает ожидаемые игры, время до релиза, описание, интерес стримера и список рекомендовавших;
- лист `СОВЕТЫ` список уже вышедших рекомендованных игр, дата релиза, оценка, рекомендовавшие;
- часть колонок заполняется вручную и сохраняется при безопасной синхронизации;
- ссылка на таблицу для чата передаётся через переменную окружения `GAMES_SHEET_URL`.

Для синхронизации нужен service account файл [config/credentials.json](config/credentials.json). В репозитории есть шаблон [config/credentials.example.json](config/credentials.example.json).

`Google Sheets` остаётся рабочим UI; постепенно его заменяет веб-интерфейс на базе [backend/](backend) (см. раздел ниже).

Пример таблицы: https://bit.ly/4bGaXC0

## Telegram-анонсы

Бот следит за Telegram-каналом и после завершения стрима находит соответствующий
анонс, после чего дописывает в него ссылку на запись (VOD).

- управляется переменными `TELEGRAM_ENABLED`, `TELEGRAM_BOT_TOKEN`,
  `TELEGRAM_CHANNEL_ID` (по умолчанию `TELEGRAM_ENABLED=false` — код есть, но
  ничего не опрашивает);
- `TELEGRAM_CHANNEL_ID` должен быть числовым id канала (`-100…`);
- ссылка на канал выводится из основного канала, отдельно задавать не нужно;
- пошаговый план и детали — [docs/TELEGRAM.md](docs/TELEGRAM.md).

## Веб-приложение (FastAPI + React)

Пакет [backend/](backend) — `FastAPI`-приложение, которое вместе с
[frontend/](frontend) заменяет `Google Sheets` как UI. Читает и пишет те же
данные в `PostgreSQL` (общая схема), используя доменную логику проекта.
Авторизация — Twitch OAuth + cookie-сессии.

- точка входа API: `backend.main:app`;
- API под префиксом `/api/v1`, документация — `/docs`;
- запуск API локально:

  ```bash
  .venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8001
  ```

- запуск фронтенда:

  ```bash
  cd frontend
  npm install
  npm run dev
  ```

- запуск в Docker: сервис `backend` в `docker-compose.yml`
  (`docker compose up -d --build backend`);
- контракт API: [docs/API.md](docs/API.md);
- структура и дизайн-токены фронтенда: [docs/FRONTEND.md](docs/FRONTEND.md).

Для веб-входа задайте в `.env` `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`,
`TWITCH_REDIRECT_URI`, а также `BACKEND_CORS_ORIGINS`/`BACKEND_FRONTEND_URL`
(см. [.env.example](.env.example)). Миграции применяются автоматически при
старте сервиса `backend` (`alembic upgrade head`).

## Структура проекта

- [bot.py](bot.py) — точка входа бота.
- [core](core) — инициализация бота и загрузка команд.
- [commands](commands) — обработчики чат-команд.
- [services](services) — бизнес-логика, GPT, HLTB, Sheets и прочие интеграции.
- [runtime](runtime) — сбор live-метрик стрима (Runtime Stream Collector).
- [telegram](telegram) — правка Telegram-анонсов после стрима.
- [backend](backend) — веб-бэкенд на `FastAPI` (`backend.main:app`).
- [frontend](frontend) — React-приложение (Vite, TypeScript, Tailwind 4).
- [database](database) — модели и работа с `PostgreSQL` (SQLAlchemy async + Alembic).
- [pipeline](pipeline) — ETL-пайплайн для сбора и обработки данных.
- [storage](storage) — локальные данные, кэш, база и runtime-файлы.
- [config](config) — конфигурация и credentials.
- [docs](docs) — документация: архитектура, команды, БД, источники, API,
  фронтенд, Telegram.

## Конфигурация

Основные настройки лежат в `.env`:
- `TWITCH_TOKEN`, `TWITCH_NICK`, `TWITCH_CHANNEL` (или `TWITCH_CHANNELS`) для подключения к Twitch;
- `CLIENT_ID`, `CLIENT_SECRET` для Twitch API;
- `DATABASE_URL` для подключения к PostgreSQL;
- `IGDB_CLIENT_ID`, `IGDB_CLIENT_SECRET` (fallback на `CLIENT_ID`/`CLIENT_SECRET`);
- `GEMINI_API_KEY`, `GEMINI_MODEL`, `OPENROUTER_API_KEY` для LLM;
- `GAMES_SHEET_URL` для публичной ссылки на таблицу в ответах `!игры` и `!стримы`;
- `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`, `TWITCH_REDIRECT_URI`, `TWITCH_SCOPE` для веб-входа (OAuth);
- `BACKEND_*` (`BACKEND_HOST`, `BACKEND_PORT`, `BACKEND_CORS_ORIGINS`, `BACKEND_FRONTEND_URL`, cookie/CSRF) для веб-бэкенда;
- `TELEGRAM_ENABLED`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHANNEL_ID` для Telegram-анонсов.

Примеры:
- [.env.example](.env.example)
- [storage/info.example.json](storage/info.example.json)

Локально также используются:
- `storage/info.json` — база ответов для `!инфо`;
- `storage/info_aliases.json` — алиасы и варианты запросов;
- файлы в `storage/cache`, `storage/config`, `storage/pages`;
- `storage/*.json` с рабочими данными.

## Запуск

Локально:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# PostgreSQL
docker compose up -d db
python -m alembic upgrade head

# бот
python bot.py

# веб-бэкенд (API + OAuth)
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8001

# фронтенд (в отдельном терминале)
cd frontend
npm install
npm run dev
```

Через Docker:

```bash
# весь проект (db + bot + backend)
docker compose up -d --build

# только веб-бэкенд
docker compose up -d --build backend
```

Веб-бэкенд доступен на `http://localhost:8001` (`/docs` — документация).
Фронтенд в Docker не входит — запускайте его отдельно, `http://localhost:5173`.
При старте сервиса `backend` автоматически применяются миграции
(`alembic upgrade head`).

> Внутри Docker-сети `DATABASE_URL` должен указывать на `db:5432`, а не на
> `localhost` (например,
> `postgresql+asyncpg://postgres:postgres@db:5432/mishgan_bot`). Значение из
> локального `.env` с `localhost` подходит только для запуска вне контейнеров.

Перед запуском нужно подготовить:
- `.env` на основе [.env.example](.env.example);
- при необходимости `config/credentials.json`;
- при необходимости локальные данные в `storage`.

## Данные и ограничения

- Бот подключается к каналу(ам), указанным в `TWITCH_CHANNEL` или `TWITCH_CHANNELS` (через запятую).
  Первый канал в `TWITCH_CHANNELS` считается основным (EventSub/статистика/анонсы).
- Некоторые команды доступны только модераторам или staff-ролям (см. `docs/CHAT_COMMANDS.md`).
- Без `Google Sheets` интеграции бот продолжит работать, но ответы `!игры` и `!стримы` будут без полезной ссылки на таблицу.
- Без `storage/info.json` команда `!инфо` использует пример из репозитория.
- Веб-бэкенд требует настроенного Twitch OAuth (`TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`, `TWITCH_REDIRECT_URI`); иначе `/api/v1/auth/login` отвечает `503`.
- Telegram-анонсы по умолчанию выключены (`TELEGRAM_ENABLED=false`).
- В Docker сервисы `bot` и `backend` поднимаются с `restart: unless-stopped`, миграции применяются при старте `backend`.

## Зависимости

Основные библиотеки:
- `twitchio`
- `aiogram`
- `SQLAlchemy[asyncio]`
- `asyncpg`
- `alembic`
- `fastapi`
- `uvicorn[standard]`
- `pydantic-settings`
- `cryptography`
- `gspread`
- `oauth2client`
- `howlongtobeatpy`
- `google-genai`
- `openai`
- `g4f`
- `beautifulsoup4`
- `aiohttp`

Список пакетов: [requirements.txt](requirements.txt).

## Проверки

```powershell
.venv\Scripts\python.exe -m pytest tests -q
cd frontend
npm run lint
npm run typecheck
npm test
```

Тесты покрывают backend API/схемы/репозитории, authz и Telegram. Для запуска
`pytest` установите зависимости из `requirements.txt` и сам `pytest`.

## Планы развития

- расширение списка команд и функций бота;
- развитие веб-интерфейса: команды, ивенты, интерактив, расширенная админка;
- инструменты для аналитики и прогнозирования.
