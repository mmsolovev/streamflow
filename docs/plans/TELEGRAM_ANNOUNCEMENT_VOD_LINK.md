# Автоподстановка ссылки на запись в Telegram-анонс

Пошаговый план реализации: после окончания стрима бот сам находит анонс стрима
в Telegram-канале и заменяет его текст на сообщение со ссылкой на VOD.

Статус документа: реализация. Этапы 1–6 выполнены, этап 7 — частично,
этап 8 (переключение на боевой канал) — не начат.
Обновлён: 2026-10-01.

Актуально на 2026-10-01: подпись собирается как текст + `entities` (без
`parse_mode`), кастомный эмодзи стримера читается из анонса и переиспользуется
при правке. Права бота на основном канале проверены — не хватает только
переключения `TELEGRAM_ENABLED` и `TELEGRAM_CHANNEL_ID` в `.env`.

---

## 1. Цель

Сейчас цикл ручной:

1. Стример публикует в Telegram-канале анонс: картинка + подпись вида
   `Стрим онлайн <ссылка на Twitch-канал>`.
2. Стрим идёт, бот ловит `stream.offline` через EventSub.
3. Стример вручную запускает `python -m pipeline.orchestrator.sync_vods`,
   который синхронизирует `stream_recordings` с архивом Twitch.
4. Стример вручную редактирует пост, заменяя текст на
   `Запись стрима:` и кликабельную подпись `💬TWITCH~`.

Целевой цикл: шаги 3–4 автоматизируются, вместо ручной правки появляется цепочка

```
stream.offline ──► через 11 минут найти VOD ──► отредактировать подпись анонса
```

Возможные проблемы и их решения — раздел 11.

---

## 2. Итоговые решения

| Вопрос | Решение |
|---|---|
| Библиотека | `aiogram==3.31.0`. Polling запускается как таска внутри event loop twitchio-бота, второй loop не создаётся |
| Формат анонса | Одна картинка + подпись со ссылкой на канал. Дополнительно поддерживается текстовый пост без медиа |
| Что считать анонсом | **Ссылка на `twitch.tv/<TWITCH_PRIMARY_CHANNEL>`**, а не слова в подписи. Подпись меняется — ссылка стабильна |
| Шум в канале (новости, реклама, репосты) | Репосты отсекаются полем `forward_origin`; остальное — окном времени и требованием ссылки на канал |
| Время проверки VOD | Один вызов через `TELEGRAM_VOD_CHECK_DELAY_SECONDS = 660` (11 минут) после `stream.offline` |
| VOD не появился | `WARNING` в лог, `status = 'no_vod'`, пост **не меняется** |
| Краш трансляции / перезапуск broadcast | Один пост может получить несколько VOD-ссылок; текст пересобирается из списка |
| Ручной запуск | `utils/telegram_vod_link.py` |
| Текст | Жёсткий шаблон в `telegram/templates.py`, позже выносится в `.env` |
| Картинка | Не трогается. `edit_message_caption` / `edit_message_text` меняют только текст |
| Каналов | Один, `TELEGRAM_CHANNEL_ID`. Переключение тест → боевой — правкой `.env`. Несколько каналов — фаза 2 |
| Команды боту | Не нужны. Ручные операции — через CLI в `utils/` |
| Сообщения от бота в канал | Запрещены. Бот только логирует и правит подпись анонса |
| Лишние правки постов | Запрещены. Одна правка на стрим, только при найденном VOD |

---

## 3. Что переиспользуется из проекта

| Актив | Назначение |
|---|---|
| `services/eventsub_service.py:229` `on_stream_start` | точка входа события старта |
| `services/eventsub_service.py:243` `on_stream_end` | точка входа события окончания |
| `runtime/collector.py:281` `storage.append_completed_session` | финализация сессии, есть `stream_id`, `started_at`, `ended_at` |
| `pipeline/ingest/twitch_api.py:27` `fetch_user_id` | user id канала |
| `pipeline/ingest/twitch_api.py:51` `fetch_vods` | список VOD, в каждом объекте есть поле `stream_id` |
| `pipeline/transform/streams_transform.py:91` `extract_stream_id_from_vod` | чтение `stream_id` из VOD |
| `services/token_service.py:145` `try_refresh_token` | рефреш токена при 401 |
| `database/models.py:485` `StreamRecording` | существующее место хранения ссылок на записи |
| `services/deferred_service.py` | паттерн фоновой задачи |
| `utils/inflight.py:12` `run_once` | паттерн дедупликации |
| `utils/logger.py:12` `configure_logging` | aiogram-логи наследуют root-логгер |
| `utils/authorize_twitch_token.py:22` | паттерн `sys.path.insert` для скриптов в `utils/` |
| `pipeline/orchestrator/sync_vods.py:41` `_parse_vod_duration` | парс `"7h29m15s"` → минуты |

Telegram в проекте отсутствует полностью: 0 совпадений по `telegram|aiogram`,
в `.venv` нет ни `aiogram`, ни `python-telegram-bot`. Есть только `aiohttp`.

---

## 4. Ключевое наблюдение

Twitch `GET /helix/videos` возвращает в каждом объекте VOD поле `stream_id`.

Значит **матчить VOD к стриму не нужно**: достаточно отфильтровать
`vod["stream_id"] == <stream_id из runtime-сессии>`. Никакой эвристики по датам
и заголовкам, никакой зависимости от наличия строки в таблице `streams`
и от работы `sync_vods`.

Это же делает обработку краша тривиальной: каждый перезапуск трансляции — новый
`stream_id`, у него свой VOD, и все они принадлежат одному анонсу.

---

## 5. Архитектура

### 5.1. Поток данных

```
┌───────────────────────────────────────────────────────────────────────┐
│ Twitch EventSub (stream.offline)                                     │
└───────────────────────────────┬───────────────────────────────────────┘
                                │ stream_id, started_at, ended_at
                                ▼
┌───────────────────────────────────────────────────────────────────────┐
│ RuntimeStreamCollector.finalize_active_session   runtime/collector.py │
│   └── finalize-listener → TelegramService.on_stream_ended(session)    │
│         │                                                             │
│         ├─ SELECT кандидата-поста (см. 6.2)                          │
│         │     window + ссылка на twitch.tv/<channel>                  │
│         │     + не forward + ещё не занят                            │
│         │     fallback: переиспользование поста прошлого стрима (6.4)  │
│         │                                                             │
│         └─ INSERT telegram_announcement_vods                          │
│              status='waiting', check_at = now + 660                   │
└───────────────────────────────┬───────────────────────────────────────┘
                                │
┌───────────────────────────────▼───────────────────────────────────────┐
│ Telegram getUpdates (aiogram, long-poll в том же loop)               │
│   channel_post / edited_channel_post                                  │
│     └── UPSERT telegram_announcements (status='observed')             │
└───────────────────────────────┬───────────────────────────────────────┘
                                │
┌───────────────────────────────▼───────────────────────────────────────┐
│ VOD-поллер (каждые 60с)                                               │
│   SELECT * FROM telegram_announcement_vods                            │
│    WHERE status='waiting' AND check_at <= now()                      │
│     └── vod_service.fetch_vod_for_stream(stream_id)                   │
│           ├─ VOD найден                                                │
│           │     ├── upsert stream_recordings (если есть streams-строка)│
│           │     ├── UPDATE vod-row → status='resolved', vod_url       │
│           │     └── пересобрать текст из ВСЕХ resolved VOD поста      │
│           │           └── edit_message_caption / edit_message_text    │
│           │                 └── announcement.status = 'edited'        │
│           │                                                            │
│           └─ VOD не найден                                             │
│                 ├── WARNING в лог                                     │
│                 └── vod-row → status='no_vod'   (пост не трогаем)     │
└───────────────────────────────────────────────────────────────────────┘
```

### 5.2. Компоненты

```
telegram/                  ← верхний уровень, рядом с runtime/ и pipeline/
  ├── __init__.py
  ├── service.py        TelegramService — жизненный цикл, точки входа, VOD-поллер
  ├── handlers.py       @dp.channel_post / @dp.edited_channel_post
  ├── announcements.py  работа с telegram_announcements (repository)
  ├── vod_jobs.py       работа с telegram_announcement_vods (repository)
  ├── matcher.py        чистые функции: матчинг кандидата, правила окна
  ├── templates.py      жёсткие текстовые шаблоны
  └── vod_service.py    поиск VOD по Twitch stream_id

utils/telegram_vod_link.py    ручной запуск / диагностика
```

Пакет лежит на верхнем уровне, а не в `services/`, потому что это
самостоятельный потребитель: свой long-poll через aiogram, своё состояние в
PostgreSQL, своя точка входа (хук на `RuntimeStreamCollector`). Он читается
как отдельный слой, а не как ещё один сервис бота, и его видно целиком при
выделении в микросервис — импортов из `core/`, `commands/` не будет, только
`database`, `pipeline.ingest`, `services.token_service`, `utils`.

Имя `telegram` перекрывает одноимённый сторонний пакет (`python-telegram-bot`).
В проекте он не используется, весь доступ к Bot API идёт через aiogram; при
появлении такой зависимости будет конфликт импортов.

Собственного `telegram/settings.py` нет: настройки читаются из `config.settings`,
как это делают `services/*` и `runtime/*`.

---

## 6. Алгоритмы

### 6.1. Приём постов (`handlers.py`)

Обрабатываются три апдейта:

| Апдейт | Действие |
|---|---|
| `channel_post` | вставить/обновить запись, `status = 'observed'` |
| `edited_channel_post` | обновить снапшоты текста; выставить `manually_edited` |
| `message` / `edited_message` | игнорируются (чат, а не канал) |

Действия при `edited_channel_post`:

- если запись в статусе `edited` или `skipped` → `manually_edited = True`
- если запись в статусе `waiting` (пост уже привязан, ждём VOD) →
  `manually_edited = True`, статус → `skipped`, **пост больше не правится**
- всегда обновляются `text_snapshot` / `caption_snapshot`

Эхо собственной правки: `edit_message_caption` порождает `edited_channel_post`,
который вернётся в хендлер. Защита двухслойная:

1. `announcement.status` выставляется в `edited` **до** вызова API;
2. `announcements.py` хранит `edited_text`, и хендлер сверяет входящий текст с ним.

### 6.2. Выбор поста-кандидата (`matcher.py` + `vod_jobs.py`)

Чистые функции `matcher.py` (покрываются юнит-тестами, I/O не делают):

| Функция | Правило |
|---|---|
| `has_channel_link(text, matcher)` | ссылка на канал стримера: хост ровно `twitch.tv` / `www.` / `m.`, последний сегмент пути — ровно логин. Ссылка проверяется целиком через `urlsplit`, а не поиском подстроки, иначе `https://example.com/?ref=twitch.tv/tabula` дал бы ложную привязку |
| `is_already_finished(text)` | текст содержит «оконч» или `twitch.tv/videos/` → пост уже обработан. Слово «запись» **не** входит: «запись будет завтра» в анонсе — нормальный текст, и ложное срабатывание потеряло бы стрим |
| `in_window(posted_at, started_at, ended_at)` | `started_at - BEFORE <= posted_at <= ended_at + AFTER`, границы включительные |
| `in_rebind_window(prev_ended_at, new_started_at)` | `prev_ended_at >= new_started_at - REBIND_WINDOW` → новый стрим продолжает старый анонс |
| `pick_candidate(posts, ...)` | самый свежий прошедший все фильтры |
| `normalize_dt`, `normalize_text`, `extract_urls`, `post_text` | приведение Telegram/runtime значений к общему виду |

Проверка репоста — не чистая функция: `message.forward_origin is not None`
разбирается в `handlers.py` и кладётся в колонку `is_forward`.

Порядок выборки кандидата при `stream.offline`:

1. Посты с `stream_id IS NULL`, прошедшие `is_forward` / `has_channel_link` /
   `in_window` → берём самый свежий.
2. Кандидата нет → правило переиспользования (6.4).

### 6.3. Разрешение VOD (`telegram/vod_service.py`)

```
fetch_user_id(primary_channel)
  → при TwitchTokenExpiredError: try_refresh_token() и повтор
fetch_vods(first=20, max_items=20, type="archive")
  → [v for v in vods if str(v["stream_id"]) == stream_id]
  → max(candidates, key=_parse_vod_duration)
```

`fetch_vods` сейчас листает **весь** архив канала постранично. Для горячего пути
добавляется параметр `max_items`, чтобы при `stream.offline` тянуть только 20
последних записей.

Ошибки инфраструктуры (сеть, 5xx) → `last_error`, `attempts += 1`,
`check_at = now + 120`, повтор до `TELEGRAM_VOD_MAX_ATTEMPTS = 5`.
Ошибка бизнес-логики (VOD нет в ответе) → терминальный `no_vod`.

### 6.4. Краш трансляции и переиспользование поста

Сценарий: трансляция падает в 21:00, стример перезапускает broadcast в 21:05.
Новый `stream_id`, новый VOD, а нового анонса стример не публикует.

Правило: если свежих кандидатов нет, берётся пост, у которого уже есть
`vod_jobs`-строка с `stream_ended_at >= started_at_нового_стрима - TELEGRAM_REBIND_WINDOW_MINUTES`
(по умолчанию 180 минут). Этот пост считается продолжением того же анонса.

Текст при этом **пересобирается целиком** из списка resolved VOD, а не
дописывается в текущий. Поэтому результат детерминирован и идемпотентен:

```
resolved VOD поста, отсортированные по stream_started_at:

1 ссылка   → "Запись стрима:\n\n💬TWITCH~"
2+ ссылки  → "Запись стрима:\n\n💬TWITCH~\n💬TWITCH~"
```

Видимый текст — как пишет стример от руки. URL в нём не участвует: ссылка
отображается подписью `💬TWITCH~`, сам адрес уходит в `href` тега `<a>`.
Под версией `parse_mode=HTML` уходит:

```
Запись стрима:

<a href="https://twitch.tv/videos/123">💬TWITCH~</a>
```

Порядок задаётся колонкой `stream_started_at` в `telegram_announcement_vods`,
поэтому внешние таблицы не нужны. Порядок виден только в HTML: подписи ссылок
одинаковые, в текстовой версии номера не отличаются.

**Про `is_already_finished`.** Смена формата сломала маркеры готового поста: в
подписи больше нет ни `twitch.tv/videos/`, ни слова «оконч». Добавлен маркер
`запись стрима:` — с двоеточием, иначе он ловил бы «Запись стрима будет через
час» в обычном анонсе и потерял бы стрим. Тем же текстом стример правит пост
вручную, поэтому такой пост тоже считается готовым.

**Про эмодзи.** `💬` — обычный Unicode (U+1F4AC). Кастомные эмодзи из наборов
стикеров так вставить нельзя: у них есть `emoji_id`, который бот узнаёт только
из уже существующего сообщения. Это отдельная задача, см. раздел 14.

### 6.5. Ручная правка стримером

Если между нашим `stream.offline` и правкой бота стример отредактировал пост
вручную, придёт `edited_channel_post` → `manually_edited = True`.
Для поста с новым VOD это означает: раздел 6.4 выполнен, ссылка записана в БД,
но **правка пропускается**, в лог пишется `WARNING`. Бот ничего не перетирает.

---

## 7. Схема данных

### 7.1. `telegram_announcements` — пост в Telegram

| Колонка | Тип | Назначение |
|---|---|---|
| `id` | BigInt PK | |
| `chat_id` | BigInt not null | id канала |
| `message_id` | Integer not null | id сообщения |
| `media_kind` | String(20) | `'photo'` или NULL — определяет метод правки |
| `media_group_id` | Text | на случай альбома |
| `is_forward` | Boolean default false | репост |
| `text_snapshot` | Text | текст на момент получения |
| `caption_snapshot` | Text | подпись на момент получения |
| `posted_at` | DateTime not null | `message.date`, naive UTC |
| `status` | String(20) not null | `observed` \| `edited` \| `skipped` |
| `edited_text` | Text | текст, который записал бот |
| `manually_edited` | Boolean default false | пост правили не мы |
| `created_at` / `updated_at` | DateTime | |

Индексы: `UNIQUE(chat_id, message_id)`, `INDEX(status)`, `INDEX(posted_at)`.

### 7.2. `telegram_announcement_vods` — задача «найти VOD для стрима»

| Колонка | Тип | Назначение |
|---|---|---|
| `id` | BigInt PK | |
| `announcement_id` | Integer FK not null | `telegram_announcements.id` |
| `stream_id` | Text not null | Twitch `stream_id` |
| `stream_started_at` | DateTime not null | для порядка ссылок и окна переиспользования |
| `stream_ended_at` | DateTime | для правила 6.4 |
| `status` | String(20) not null | `waiting` \| `resolved` \| `no_vod` \| `failed` |
| `vod_url` | Text | найденная ссылка |
| `duration_minutes` | Integer | из `vod["duration"]` |
| `recorded_at` | DateTime | из `vod["created_at"]` |
| `check_at` | DateTime | время следующей проверки |
| `attempts` | Integer default 0 | попытки при ошибках инфраструктуры |
| `last_error` | Text | |
| `created_at` / `updated_at` | DateTime | |

Индексы: `UNIQUE(announcement_id, stream_id)`, `INDEX(status, check_at)`,
`INDEX(stream_id)`.

Состояние переносится с поста на связку «пост + стрим» именно потому, что одному
посту может соответствовать несколько `stream_id` после краша.

### 7.3. Про `update_id`

Отдельная таблица для `update_id` **не нужна** осознанно: aiogram после рестарта
начинает long-poll с самых ранних неподтверждённых апдейтов, то есть пропусков
постов не будет, а дубли гасит идемпотентный upsert по `(chat_id, message_id)`.

---

## 8. Изменения в существующих файлах

| Файл | Изменение |
|---|---|
| `requirements.txt` | добавить `aiogram==3.31.0` |
| `config/settings.py` | 9 новых переменных (раздел 9) |
| `.env.example` | те же ключи с пустыми значениями |
| `database/models.py` | `TelegramAnnouncement`, `TelegramAnnouncementVod` |
| `alembic/versions/0008_add_telegram_announcements.py` | новая миграция, `down_revision = "0007"` |
| `runtime/collector.py` | список finalize-листенов + вызов в `finalize_active_session` после строки 281 |
| `core/bot.py` | в `event_ready` (строка 43) создать `TelegramService`, зарегистрировать листенер, стартовать поллинг и VOD-поллер как таски |
| `pipeline/ingest/twitch_api.py` | параметр `max_items` в `fetch_vods` |
| `telegram/vod_service.py` | **новый** |
| `telegram/` | **новый пакет** |
| `utils/telegram_vod_link.py` | **новый** |
| `docs/ARCHITECTURE.md` | раздел 7 «Известные узкие места»: пункт «Нет API для веба/телеграма» снимается; добавить Telegram в диаграмму Consumers |
| `README.md` | раздел «Зависимости», «Запуск», «Данные и ограничения» |
| `docker-compose.yml` | комментарий: поллер запускается только в сервисе `bot` |

### 8.1. Хук на `runtime/collector.py`

Событие окончания стрима финализируется не только через `stream.offline`:
`finalize_active_session` вызывается ещё из `handle_stream_online`
(`superseded_by_new_stream_online`) и из `bootstrap`
(`recovered_offline_on_bootstrap`, `recovered_new_live_stream_on_bootstrap`).
Поэтому хук вешается на уровне финализации, а не на `EventSubService`:

```python
def __init__(...):
    self._finalize_listeners: list[Callable[[dict], None]] = []

def add_finalize_listener(self, listener):
    self._finalize_listeners.append(listener)

async def finalize_active_session(self, *, ended_at: str, reason: str):
    ...
    storage.append_completed_session(session, reason)          # существующая строка 281
    for listener in list(self._finalize_listeners):
        try:
            result = listener(session)
            if inspect.isawaitable(result):
                await result
        except Exception:
            self.logger.exception("finalize listener failed for session %s",
                                  session.get("stream_id"))
```

Плюсы: покрываются все пути завершения, `runtime/` не знает про Telegram
(в listener передаётся `session` целиком: `stream_id`, `started_at`, `ended_at`,
`title`, `collector.completion_reason`), а ошибка listener'а не ломает сборщик.

Отдельный хук в `services/eventsub_service.py:243` не делается — он покрыл бы
только один из путей и потребовал бы снимать `stream_id` из
`collector.active_session` до вызова `handle_stream_offline()` (строка 110
обнуляет сессию в `finalize_active_session`).

---

## 9. Конфигурация

```dotenv
# Главный переключатель. Пока выключен — ни поллер, ни правки не работают.
TELEGRAM_ENABLED=false
TELEGRAM_BOT_TOKEN=

# Один канал. Переключение тест → боевой — правкой этой строки.
# Формат: @username или -100xxxxxxxxxx
TELEGRAM_CHANNEL_ID=

# Через сколько секунд после окончания стрима проверять наличие VOD.
TELEGRAM_VOD_CHECK_DELAY_SECONDS=660

# Как часто поллер опрашивает БД на предмет задач check_at <= now().
TELEGRAM_VOD_POLL_INTERVAL_SECONDS=60

# Повторы при ошибках инфраструктуры (сеть, 5xx), не при отсутствии VOD.
TELEGRAM_VOD_MAX_ATTEMPTS=5

# Окно, в котором ищем анонс относительно стрима.
TELEGRAM_MATCH_WINDOW_BEFORE_HOURS=12
TELEGRAM_MATCH_WINDOW_AFTER_MINUTES=60

# Если трансляция падала и broadcast перезапускался — насколько поздно
# предыдущий стрим ещё считается частью того же анонса.
TELEGRAM_REBIND_WINDOW_MINUTES=180

# Домены, на которые смотрим в тексте поста при поиске анонса.
TELEGRAM_LINK_DOMAINS=twitch.tv
```

Ссылка на канал **не** дублируется в `.env`, а выводится из существующего
`TWITCH_PRIMARY_CHANNEL`.

Переменные, которые сознательно **не** заводим: `TELEGRAM_ADMIN_USER_IDS`
(команд нет), `TELEGRAM_FINISHED_TEMPLATE` (текст жёсткий, раздел 2),
`TELEGRAM_CHANNEL_IDS` (один канал, несколько — фаза 2).

---

## 10. Пошаговый план реализации

### Этап 1. Каркас без побочных эффектов — **выполнен**

Ничего не включаем в проде, только готовим код и чистые функции.

- [x] `requirements.txt` → `aiogram==3.31.0`; `pip install -r requirements.txt`;
      проверить, что `aiohttp 3.14.3` не конфликтует (aiogram требует `>=3.9.0`)
- [x] `config/settings.py` — 9 переменных из раздела 9 + парсер списка доменов
- [x] `.env.example` — те же ключи
- [x] `database/models.py` — `TelegramAnnouncement`, `TelegramAnnouncementVod`
- [x] `alembic/versions/0008_add_telegram_announcements.py`, `down_revision = "0007"`;
      `alembic upgrade head`, проверить `alembic downgrade -1` и повторный upgrade
- [x] `telegram/templates.py` — `build_finished_text(urls: list[str]) -> str`
      и `FINISHED_SINGLE` / `FINISHED_MULTI`
- [x] `telegram/matcher.py` — `is_forward`, `has_channel_link`,
      `is_already_finished`, `in_window`, `pick_candidate` (без I/O)
- [x] Юнит-тест на `matcher.py` и `templates.py`:
      - подпись со ссылкой в конце строки / в середине / с `www.`
      - репост отсекается
      - пост без ссылки отсекается
      - пост «Стрим окончен. Запись …» считается уже обработанным
      - 1 VOD и 3 VOD дают разные шаблоны, порядок сохраняется

**Приёмка:** миграция проходит, тесты зелёные, бот стартует как раньше,
`TELEGRAM_ENABLED=false` и в логах нет ни одного упоминания Telegram.

**Фактические отличия от плана:**

- Тесты на stdlib `unittest`, без `pytest`: в образе Docker его нет, а тащить
  ради 80 тестов ещё одну зависимость не хочется.
  Запуск: `.venv\Scripts\python.exe -m unittest discover -s tests -t .`
- Ссылка на канал ищется разбором каждой ссылки через `urlsplit`, а не
  регуляркой по подстроке. Регулярка ловила бы
  `https://example.com/?ref=twitch.tv/tabula` — то есть привязала бы анонс
  по чужой ссылке. Тип — `ChannelLinkMatcher`, не `re.Pattern`.
- Из маркеров «уже обработанного» убрано слово «запись»: фраза
  «запись будет завтра» в анонсе — обычный текст, и ложное срабатывание
  потеряло бы стрим.
- Тесты лежат в `tests/`, а не в `telegram/tests.py` — их видно и в IDE,
  и в `unittest discover`.

### Этап 2. aiogram-сервис, только чтение постов — **выполнен**

Первый этап, который требует настроек в Telegram. Ничего не правим.

- [x] `telegram/service.py` — `TelegramService.start()`:
      ```
      tg_bot = Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
      dispatcher = Dispatcher()
      register_handlers(dispatcher)
      await dispatcher.start_polling(tg_bot, handle_signals=False,
                                     allowed_updates=["channel_post",
                                                      "edited_channel_post"])
      ```
      Вызов из `core/bot.py` `event_ready`.
      `handle_signals=False` — `add_signal_handler` на Windows кидает
      `NotImplementedError` (в aiogram заглушено, но полагаться на это не нужно)
- [x] `telegram/handlers.py` — регистрация хендлеров, только запись в БД
- [x] `telegram/announcements.py` — `record_post`, `mark_skipped`, `touch_snapshots`
- [x] Интеграция с runtime: `RuntimeStreamCollector.add_finalize_listener()`
      в `core/bot.py`, вызов — в конце `finalize_active_session`
- [x] `utils/telegram_channel_info.py` — узнать `chat_id` канала и проверить токен

**Приёмка:** в **тестовом** канале опубликован анонс → в логе
`Observed channel post …`, в таблице `telegram_announcements` строка
со `status='observed'`.

**Фактические отличия от плана:**

- `allowed_updates` содержит только `channel_post` и `edited_channel_post`.
  `message` и `edited_message` не подписаны: бот не отвечает в личных чатах
  и не реагирует на команды, подписка на них была бы лишним трафиком.
- `on_stream_ended` подписан на финализацию runtime-сессии, а не на
  `event_stream_offline`. Отдельный хук в EventSub покрыл бы не все
  сценарии: краш трансляции проходит через `superseded_by_new_stream_online`
  и `recovered_*` на bootstrap, где события окончания не было вовсе.
  Листенера вызывается один раз, уже после `append_completed_session`, и его
  ошибки логируются, но не пробрасываются — иначе упала бы запись статистики.
- `delete_webhook` не вызывается. Бот работает только на long polling, и
  сбрасывать webhook чужого бота, переведённого на webhook при отладке через
  getUpdates, значило бы сломать его работу. Ставить webhook вручную не нужно.
- `edited_channel_post` различает эхо правки бота и правку стримера через
  `templates.is_own_edit`, а не точным равенством: бот отправляет HTML,
  Telegram возвращает отрендеренный текст, и при обрезке по лимиту строки
  расходятся. Сравнение по префиксу покрывает оба случая.
- `announcements.mark_skipped` вызывается и для постов в статусе `observed`,
  если стример отредактировал их до привязки к стриму: иначе такой пост
  мог бы выиграть выборку по свежести.

### Этап 3. Поиск VOD, Telegram не трогаем — **выполнен**

- [x] `pipeline/ingest/twitch_api.py` — `fetch_vods(..., max_items: int | None = None)`,
      ранний выход из пагинации
- [x] `telegram/vod_service.py` — `fetch_vod_for_stream(stream_id) -> dict | None`
      с рефрешем токена по образцу `sync_vods.py:71`
- [x] `telegram/vod_jobs.py` — очередь задач с отложенной проверкой
- [x] `utils/telegram_vod_link.py` — CLI, dry-run по умолчанию, правка только с `--apply`

**Приёмка:** после реального стрима `python utils/telegram_vod_link.py --stream-id <id>`
печатает найденный VOD; в таблице `telegram_announcements` **ничего не изменилось**.

**Фактические отличия от плана:**

- `--dry-run` заменён на `--apply` по умолчанию: скрипт без флагов только
  печатает, и это безопаснее, чем отдельный флаг «не делать».
- VOD ищется по точному `stream_id`, а не «самый длинный из архива».
  При нескольких записях одного `stream_id` берётся самая длинная.
- Токен обновляется один раз на вызов и на два запроса (`/users`, `/videos`):
  бесконечный ретрай на битом refresh token зациклил бы поллер.
- Ошибки инфраструктуры и «VOD не найден» разведены: `VodLookupError` ведёт
  к ретраю с растущей паузой (120с → 1800с, 5 попыток), отсутствие VOD в
  архиве — терминальный `no_vod` без правки поста.
- Длительность в минутах считается как `int(x / 60 + 0.5)`, а не `round()`:
  в Python `round(62.5) == 62`, и пост показывал бы минуту меньше фактической.

### Этап 4. Привязка поста к стриму — **выполнен**

- [x] `telegram/service.py` — `on_stream_ended(session)`,
      регистрация листенера в `runtime/collector.py`
- [x] `telegram/matcher.py` — выбор кандидата (6.2)
- [x] `telegram/vod_jobs.py` — `create_job`, `claim_due`, `mark_resolved/no_vod/failed`
- [x] `core/bot.py` — запуск VOD-поллера (раз в 60с) как таски

**Приёмка:** в логе `Announcement … bound to stream … VOD check in 660s`,
в `telegram_announcement_vods` строка `status='waiting'`, `check_at ≈ +11 мин`.
Пост в Telegram **ещё не изменён**.

### Этап 5. Первая правка поста — **выполнен**

Первый шаг, меняющий Telegram-канал. Только на тестовом канале.

- [x] `telegram/service.py` — `_apply_edit()`:
      `edit_message_caption` при `media_kind == 'photo'`, иначе `edit_message_text`;
      `parse_mode=HTML`; статус в `edited` + `edited_text` **до** вызова API
- [x] Обработка ошибок aiogram: `TelegramBadRequest` (`message is not modified`),
      прочие — логируются и переводят анонс в `skipped`
- [x] Ограничение длины: caption ≤ 1024 символа, при превышении — обрезать с
      многоточием до вставки
- [x] Пересборка текста из всех `resolved` VOD поста (6.4)

**Приёмка:** через 11 минут после окончания стрима подпись анонса стала
`Запись стрима:` + `💬TWITCH~` со ссылкой на VOD, картинка на месте,
`status='resolved'` и `announcement.status='edited'`, в логе нет ошибок.

**Требует ручной проверки на тестовом канале:** права администратора
(`CHAT_ADMIN_REQUIRED`) проверяются именно здесь.

- [ ] Проверить правку реального анонса на тестовом канале

### Этап 6. Отсутствие VOD и краш трансляции

- [ ] `mark_no_vod` — `WARNING` в лог с `stream_id`, `chat_id`, `message_id`
- [ ] Правило переиспользования поста (6.4) и двухшаблонный текст
- [ ] Проверка на тестовом канале: обрыв трансляции и перезапуск broadcast
      вручную (или через `twitch` → «End Stream» → «Go Live»)

**Приёмка:** после краша в логе один `WARNING` на первый стрим, затем при
появлении второго VOD — текст с двумя ссылками в правильном порядке.

### Этап 6. Отсутствие VOD и краш трансляции — **выполнен**

- [x] `no_vod`: пост не трогаем, пишем предупреждение в лог
- [x] Ретраи с растущей паузой: 120с → 1800с, максимум 5 попыток, потом `failed`
- [x] Краш трансляции: `on_stream_ended` вызывается при каждой финализации
      runtime-сессии, поэтому связка «пост ↔ стрим» переиспользуется для
      второго `stream_id` — пост получает несколько ссылок
- [x] `templates.build_finished_text` для 1 и N VOD

**Приёмка:** после краша бота в логе два `bound to stream …` для одного
`message_id`; в посте перечислены оба VOD.

### Этап 7. Ручной запуск и диагностика — **частично**

- [x] `utils/telegram_vod_link.py`, флаги:
      - `--stream-id ID` — найти VOD для стрима
      - `--message-id ID` — привязать пост к стриму вручную
      - `--channel-id ID` — показать последние посты с их статусами
      - `--list` — все записи `telegram_announcements` + `telegram_announcement_vods`
      - `--apply` — выполнить правку (без флага только печатает)
- [ ] Восстановление после простоя: при старте сканировать
      `storage/runtime/completed_stream_sessions.json` на сессии с `ended_at`
      за последние 6 часов, у которых нет строки в `telegram_announcement_vods` →
      создать `status='waiting'` с `check_at` в прошлом (обработается сразу).
      Это закрывает пропущенный `stream.offline`, когда бот был офлайн

**Приёмка:** `--list` показывает связку пост↔стрим↔VOD; после остановки бота
на час во время стрима и перезапуска цепочка доходит до конца сама.

**Не сделано осознанно:** восстановление из `completed_stream_sessions.json`
(пункт выше). Файл есть и хук его пишет, но автоподстановка отсутствует:
пока бот работает без даунтаймов, лишний парсинг файла на старте — это
код без проверяемого сценария. Сделать, если бот реально будет выпадать.

### Этап 8. Переключение на боевой канал

- [x] Этапы 2–6 на тестовом канале: чтение постов, привязка, очередь, поллер
- [ ] Проверить фактическую правку анонса на тестовом канале (этап 5)
- [ ] Права администратора в **боевом** канале (раздел 11, п. 1)
- [ ] `TELEGRAM_ENABLED=true`
- [ ] `TELEGRAM_CHANNEL_ID` → id боевого канала
- [ ] Дождаться ближайшего стрима, проверить результат
- [ ] Комментарий в `docker-compose.yml` про единственный poller

---

## 11. Риски и способы их проверки

### 1. Права на редактирование постов от имени канала — главный риск

Все посты в канале идут от имени канала (анонимный админ). Бот-админ с правом
публикации может оказаться не в состоянии редактировать сообщения,
отправленные идентичностью канала.

Симптомы: `400 CHAT_ADMIN_REQUIRED`, `403 bot is not a member`,
`Bad Request: message is not modified`.

Проверяется на этапе 5 в тестовом канале. Если права не проходят — добавить бота
**анонимным администратором** (снять галочку «показывать имя бота»).

Именно поэтому порядок этапов такой: сначала только чтение постов (этап 2),
правка — на пятом шаге, и только на тестовом канале.

### 2. Одна проверка через 11 минут

Для стрима без обрыва этого достаточно. Но крупный VOD может обрабатываться
дольше, и автоссылка не появится — тихая потеря без последствий для данных.

Это сознательный компромисс. Расширение позже — одна переменная вместо одного
`check_at`: `TELEGRAM_VOD_RECHECK_DELAYS = "11,30,90"` (минуты), в
`service.py` цикл вместо одиночного таймера.

### 3. Шумный канал: новости, реклама, репосты

Отсекаются тремя фильтрами: `forward_origin` для репостов, окно времени,
требование ссылки на канал.

Остаточный риск: рекламный пост, в котором руками вставлена ссылка на Twitch-канал
и время попадает в окно стрима. Снижается сужением
`TELEGRAM_MATCH_WINDOW_BEFORE_HOURS` с 12 до 2 — анонс обычно выходит за
1–5 минут до старта.

### 4. Бот затирает ручную правку

Сценарий: стример не дождался и отредактировал пост сам, бот пришёл через
11 минут и переписал. Защита — `edited_channel_post` → `manually_edited = True`,
после чего пост не трогается (раздел 6.5).

### 5. Бот получает эхо собственной правки

`edit_message_caption` порождает `edited_channel_post`, который вернётся в хендлер
и выставит `manually_edited` на собственной правке. Защита: статус выставляется
в `edited` до вызова API плюс сверка текста с `edited_text`.

### 6. `getUpdates` — единственный потребитель

Длинный опрос может держать только один процесс. Нельзя одновременно поднимать
бота локально и в `docker compose` (сервис `bot` в `docker-compose.yml:15`) —
второй получит `409 Conflict`. Ручной скрипт из `utils/` тоже не должен поллить,
он делает только точечные вызовы методов.

### 7. Пропущенные исторические посты

`getUpdates` отдаёт только события, произошедшие после добавления бота в канал.
Разовый чек-лист перед этапом 2: добавить бота в тестовый канал → опубликовать
тестовый анонс → убедиться, что он попал в таблицу.

### 8. Двойная обработка

EventSub может доставить событие повторно, aiogram после рестарта переотдаёт
неподтверждённые апдейты. Закрывается идемпотентностью: `UNIQUE(chat_id, message_id)`,
`UNIQUE(announcement_id, stream_id)` и статус-машина. Повторный `edit` с тем же
текстом безвреден, но лишний вызов Bot API не делаем — проверяем `edited_text`.

### 9. `pydantic v2` приедет транзитивно с aiogram

В проекте его нет, конфликтов не ожидается. После установки прогнать
импорты `bot.py` и всех оркестраторов, убедиться, что `alembic` и SQLAlchemy
не затронуты.

### 10. Пропущенный `stream.offline` при офлайне бота

Закрывается восстановлением из `completed_stream_sessions.json` (этап 7, п. 2)
и тем, что хук висит на `finalize_active_session`, а не на событии EventSub.

### 11. Дрейф `external_id` — не в объёме, но по пути

`pipeline/load/load_streams.py:55` пишет в `external_id` дату стрима,
а `parse_twitchtracker.py` пишет туда Twitch `stream_id`. Если в будущем
захочется создавать `streams`-строку из рантайма, последующий
`import_json_to_db.py` перезапишет её датой и потеряет связь со стримом.

Поэтому запись в `stream_recordings` делается **только если** строка `streams`
с нужным `external_id` уже существует. Конфликта не возникает, а польза есть:
`sync_vods.py` увидит, что запись уже есть, и не будет перематывать её заново.
При удалении VOD из архива `sync_vods.py:124` почистит и строку БД.

### 12. Мёртвые ссылки — фаза 2

`sync_vods.py` удаляет `stream_recordings`, которых больше нет в архиве Twitch.
Пост в Telegram останется со ссылкой 404. В объём не входит: по условию бот
не делает лишних правок постов. Если понадобится — отдельная задача.

---

## 12. Что осознанно не делается сейчас

| Пункт | Почему |
|---|---|
| Несколько Telegram-каналов | Один канал, переключение правкой `.env`. Нужно для проверки другого функционала |
| Команды боту (`/bind`, `/vod`, `/статус`) | Не нужны, ручные операции через CLI |
| Настраиваемый текстовый шаблон | Жёсткий шаблон в `templates.py`, перенос в `.env` позже |
| Сообщения от бота в канал | Запрещено по требованию, всё в лог |
| Правка постов без найденного VOD | Запрещено по требованию |
| Автоправка мёртвых ссылок | Фаза 2 |
| Несколько попыток проверки VOD | Сейчас одна, на +11 минут |

---

## 13. Контрольный чек-лист выката

1. `alembic upgrade head` проходит, `alembic downgrade -1` и повторный `upgrade` тоже.
2. Бот стартует с `TELEGRAM_ENABLED=false` без упоминаний Telegram в логах.
3. `python bot.py` поднимается, EventSub-подписки в порядке.
4. Бот добавлен в **тестовый** канал администратором.
5. Тестовый анонс с картинкой и ссылкой появился в `telegram_announcements`
   со `status='observed'`, `media_kind='photo'`.
6. Тестовый анонс **без** картинки тоже принят, `media_kind IS NULL`.
7. Репост в тестовом канале не создал строку-кандидат (`is_forward = true`).
8. `python utils/telegram_vod_link.py --stream-id <id>` находит VOD.
9. `python utils/telegram_vod_link.py --list` показывает связку пост↔стрим↔VOD.
10. Через 11 минут после стрима подпись анонса изменилась, картинка на месте.
11. При обрыве трансляции в логе ровно один `WARNING`, пост не тронут.
12. После перезапуска broadcast текст содержит две ссылки в правильном порядке.
13. Ручная правка поста стримером не перетирается ботом.
14. Ручной запуск без `--apply` не делает ни одного вызова Bot API.
15. После перезапуска бота незавершённые задачи дорабатываются сами.
16. `docker compose up -d --build` поднимается, поллер в контейнере работает.
17. `TELEGRAM_CHANNEL_ID` переключён на канал стримера.
18. Подпись готового анонса выглядит как у стримера: `Запись стрима:` +
    `💬TWITCH~`, ссылка кликабельная, картинка на месте.
19. Если стример пишет эмодзи из набора, в `telegram_announcements` для его
    анонса сохранён `custom_emoji_id`, и подпись на запись использует тот же
    эмодзи. Без эмодзи в анонсе подпись остаётся на Unicode-`💬`.

---

## 14. Кастомные эмодзи: как это устроено

Эмодзи `💬` в подписи — Unicode-символ (U+1F4AC). Если стример ставит эмодзи
из набора стикеров, отличие не только в картинке: это другой объект Telegram
и вставляется он иначе. Ниже — как это сделано.

### Откуда берётся id

У сообщения есть `entities`, где кастомный эмодзи — сущность типа
`custom_emoji` с полем `custom_emoji_id` (например `5368324170671202286`).
У Unicode-эмодзи сущности нет: это просто символ в тексте.

Id нельзя выдумать и нельзя найти поиском — это внутренний идентификатор,
известный только из сообщения, где эмодзи уже стоит. Бот и не ищет его
специально: он разбирает `entities` того анонса, который и так проходит через
обработчик как кандидат.

`find_custom_emoji_id` выбирает эмодзи из записи о канале: приоритет у того,
чья сущность лежит **внутри** `text_link` на канал, при отсутствии вложенности
берётся ближайший к ссылке, а если ссылок в анонсе нет — первый найденный.

### Как вставляется

Не ссылкой `tg://emoji`, а **entities**: кастомный эмодзи Telegram рисует
только по сущности `custom_emoji`. Обходной путь через `tg://emoji` в
`parse_mode=HTML` требует Premium у владельца бота (Bot API 9.4 ограничил
кастомные эмодзи личными, групповыми и супергрупповыми чатами; каналы под
ограничение не попали) и всё равно не даёт того, что стример пишет руками.

Поэтому подпись уходит в Bot API как обычный текст с `entities` и **без
`parse_mode`** — Telegram запрещает смешивать entities с parse_mode. На каждый
лейбл кладутся две вложенные сущности:

```
{"type": "text_link",    "offset": 16, "length": 9, "url": "https://twitch.tv/videos/…"}
{"type": "custom_emoji", "offset": 16, "length": 2, "custom_emoji_id": "5368324170671202286"}
```

`text_link` покрывает весь лейбл `💬TWITCH~` (ссылка кликабельна целиком),
`custom_emoji` — только первый символ, иначе слово `TWITCH` тоже стало бы
анимированным значком. Вложенные entities поддерживаются с Bot API 6.0.

Текст при этом остаётся Unicode-`💬`, поэтому то, что вернётся в
`edited_channel_post`, совпадает с `edited_text`, и защита от эха своей правки
(`is_own_edit`) продолжает работать.

### Смещения считаются в UTF-16

`offset` и `length` в entities Telegram считает в кодовых единицах UTF-16,
а индексы Python-строк — в кодовых точках. `💬` — одна кодовая точка и две
кодовые единицы, поэтому любая арифметика по индексам без пересчёта сдвинула
бы все ссылки после первого эмодзи. За это отвечает `utf16_span`, а по той же
причине лимит длины (`1024` для caption, `4096` для текста) считается в
UTF-16: считая в точках, бот отдал бы Telegram подпись длиннее лимита.

### Если ссылок больше, чем влезает

Число ссылок подбирается при сборке подписи, а не обрезкой готового текста:
обрезка разрезала бы лейбл пополам и оставила `💬TWITC…` без ссылки. Вместо
этого лишние ссылки отбрасываются целиком, а в конце стоит многоточие.
`fit_entities` — страховка: она убирает сущности, чей конец вышел за конец
текста, потому что Telegram отверг бы весь caption из-за одного `offset`
за пределами строки.

### Что изменено

| Что | Зачем |
|---|---|
| `database/models.py` + миграция `0009` | колонка `custom_emoji_id` (`String`, а не `BigInteger`: Bot API отдаёт id строкой) |
| `telegram/entities.py` | разбор `custom_emoji_id`, пересчёт в UTF-16, сборка и фильтрация entities |
| `telegram/handlers.py` | `custom_emoji_id_of(message)`, чтение `caption_entities` / `entities` |
| `telegram/announcements.py` | сохранение `custom_emoji_id` в `record_post` |
| `telegram/templates.py` | `build_finished_entities`, `fit_entities` вместо HTML-шаблонов |
| `telegram/service.py` | правка с `entities` и без `parse_mode` |
| `utils/telegram_vod_link.py` | то же для ручного запуска |

Без `custom_emoji_id` в анонсе подпись собирается на Unicode-`💬` — это
рабочий запасной вариант: эмодзи не ломает ничего, просто не анимированный.