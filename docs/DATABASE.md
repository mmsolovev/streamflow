# База данных

Основная СУБД — **PostgreSQL**. Подключение задаётся `DATABASE_URL` в формате
`postgresql+asyncpg://user:password@host:5432/db`. ORM — SQLAlchemy 2 async,
сессии — `database.db.AsyncSessionLocal`, модели — `database/models.py`
(единый файл). Схема управляется Alembic.

## Конвенции

- Новые таблицы и поля — только новой миграцией в `alembic/versions/`.
  Применённые миграции не редактировать.
- Перед миграцией проверяй автогенерацию:
  `.venv\Scripts\python.exe -m alembic revision --autogenerate -m "..."`.
- Применить миграции: `.venv\Scripts\python.exe -m alembic upgrade head`.
  В Docker это делает сервис `backend` при старте.
- `alembic/env.py` берёт URL из `DATABASE_URL`; `sqlalchemy.url` в `alembic.ini`
  — только fallback.
- Даты и время в БД — naive UTC (`TIMESTAMP WITHOUT TIME ZONE`). Локальное
  время рассчитывается на фронтенде/в отображении.
- TwitchTracker показывает время канала без зоны, поэтому все его
  timestamp-поля конвертируются в UTC через `utils/time_utils.py` по
  `TWITCHTRACKER_TIMEZONE` (по умолчанию `Europe/Moscow`). Исключения:
  `parse_stream_date` и `game_stats.last_stream` — это дата-ключ и дата без
  времени, сдвиг пояса к ним не применяется. Уже накопленные строки
  нормализуются разово: `python -m pipeline.orchestrator.normalize_time --apply`
  (без `--apply` — dry-run; runtime-стримы пропускаются).
- Деньги/часы не хранить строками; часы в API — `float` с одним знаком,
  минуты — `int`.
- Legacy SQLite (`storage/streams.db`) не использовать для новой логики.

## Домены и таблицы

### Игры, стримы, статистика

| Таблица | Назначение |
|---|---|
| `games` | игры: `id`, `name` (unique), `slug`, `game_type`, `parent_game_id`, `franchise_id`, timestamps |
| `game_aliases` | альтернативные названия игр (`alias`, `normalized_alias`, `is_primary`, `source`) |
| `games_franchises` | франшизы |
| `genres`, `platforms`, `game_genres`, `game_platforms` | справочники и M2M-связи |
| `game_metadata_igdb` | IGDB-метаданные: `igdb_id`, дата релиза, оценки, описания, обложка, `raw_payload` |
| `game_metadata_hltb` | HLTB-метаданные: main story / extra / completionist, coop, multiplayer |
| `game_stats` | производные агрегаты по игре: `duration_minutes`, `streams_count`, `last_stream`, `max_viewers`; только `avg_viewers` / `followers_per_hour` приходят из TwitchTracker |
| `streams` | стримы: `external_id` (unique), title, `started_at`, `ended_at`, `duration_minutes`, viewers, followers/views gained; заполняется runtime и TT |
| `stream_titles` | история смены названий стрима |
| `stream_games` | игры внутри стрима: порядок, интервал, минуты, зрители, подписчики; источник детализации для `game_stats` |
| `stream_recordings` | единый реестр записей/VOD: `stream_id`, `source`, `url`, `twitch_stream_id` (broadcast id), `twitch_video_id`, `duration_minutes`, `recorded_at`, `is_available`; у стрима может быть несколько записей после реконнектов, истёкшие не удаляются, а скрываются (`is_available=false`) |
| `streamers_on_stream` | M2M `streams` ↔ `users` (кто участвовал) |
| `streamer_games` | M2M стример ↔ игра (интерес/статус) |
| `game_recommendations` | рекомендации игр пользователями |

### Пользователи, права, модерация

| Таблица | Назначение |
|---|---|
| `users` | Twitch-пользователи: `twitch_user_id`, `role`, `is_streamer` (Twitch-партнёр, не staff), duels-статистика |
| `user_profiles` | снапшоты профиля (login, display_name, avatar, first/last seen, `is_current`) |
| `user_restrictions` | Twitch ban / service ban: `kind`, `channel`, `source`, сроки, кто выдал |
| `moderation_audit` | аудит модераторских действий |
| `twitch_authorizations` | зашифрованные OAuth-токены обычного пользователя |
| `twitch_streamer_authorizations` | зашифрованные токены стримера с расширенными scopes |
| `web_sessions` | серверные веб-сессии: `token_hash`, `csrf_hash`, TTL |
| `twitch_rewards`, `twitch_reward_redemptions` | награды канала и их активации |
| `vip_history` | история VIP-статусов |
| `chat_messages` | сообщения основного канала: `twitch_message_id` (unique), `user_id`, `streamer_id`, `stream_id`, текст, `is_command`, `reply_parent_message_id`, `deleted_at`; хранятся бессрочно |
| `stream_chat_participants` | присутствие на стриме: `stream_id` + `user_id`, первый/последний message, счётчик сообщений |

`users.role` ограничен CHECK-ом: `owner`, `streamer`, `admin`, `editor`,
`user`. Роли и capability описаны в `services/authz_service.py`.

### Команды и контент

| Таблица | Назначение |
|---|---|
| `bot_commands` | реестр команд: name, description, `is_visible`, `is_active`, `bot_name` |
| `bot_command_aliases` | алиасы команд |
| `command_usage_logs` | статистика использования команд: `stream_id`, `invoked_name` (фактический алиас), `twitch_message_id`, `created_at` |
| `calendar_days` | календарные даты (`day`, `month`, `day_of_year`) |
| `holidays` | праздники, привязанные к `calendar_days`; заполняются `database/sync_holidays.py` из `storage/holidays.json` |
| `famous_persons` | известные люди, привязанные к `calendar_days` |
| `clips`, `clip_tags` | клипы и теги |

### Runtime live-метрики

| Таблица | Назначение |
|---|---|
| `stream_runtime_sessions` | одна сессия сбора на строку `streams` (`stream_id` unique), `twitch_stream_id`, статус, `started_at/ended_at`, `last_sample_at`, `samples_count` |
| `stream_runtime_samples` | сырые сэмплы: `sampled_at`, viewers, followers, title, category; unique `(stream_id, sampled_at)` |
| `stream_runtime_buckets` | агрегаты по 10-минутным интервалам: `bucket_start/end`, avg/max viewers, followers gained |
| `stream_stats_jobs` | очередь отложенной агрегации: `check_at`, статус, attempts, `locked_by/locked_at` |
| `stats_change_batches` | батч изменений статистики: источник (`runtime`, `twitchtracker`, `manual`, `rollback`), стрим, статус, `meta` |
| `stats_change_log` | построчные изменения: entity, `field`, `old_value`, `new_value`; база для отката |

Сборщик — `runtime/collector.py`; сессии, сэмплы и бакеты пишутся в PostgreSQL
через `runtime/repository.py`, JSON-файлы больше не являются источником истины.
Интервал — `STREAM_RUNTIME_SAMPLE_SECONDS` (по умолчанию 60 с).

При финализации runtime записывает `streams`, `stream_titles` и `stream_games`,
затем ставит задачу в `stream_stats_jobs` с `check_at = ended_at + 660 с`
(`STREAM_STATS_AGGREGATION_DELAY_SECONDS`). Воркер в процессе бота
(`runtime/aggregation_jobs.py`) пересчитывает `game_stats` идемпотентно:
`duration_minutes`, `streams_count`, `last_stream`, `max_viewers` выводятся из
`stream_games` / `streams`. `avg_viewers` и `followers_per_hour` пишет только
TwitchTracker. Расхождения TT сохраняются в истории
(`stats_change_batches.meta["tt_divergence"]`), а не перетирают детализацию.

У legacy-стримов TwitchTracker поля `stream_games.duration_minutes` и
`peak_viewers` могут быть пустыми: раньше в `game_stats` писался только
агрегат. Пересчёт трактует такие строки как «нет данных», а не ноль: минуты
игры сохраняются, максимальные зрители не уменьшаются (`--drift` такие
расхождения по минутам не показывает). После бэкфилла детализации агрегат
пересчитывается полностью.

Чат и команды основного канала (`TWITCH_PRIMARY_CHANNEL`) пишутся через
`services/chat_log_service.py`: сообщения — батчами с дедупом по
`twitch_message_id`, успешные вызовы команд — в `command_usage_logs`. Остальные
каналы из `TWITCH_CHANNELS` используются только для проверок команд.

Ручные операции:

```bash
# догнать очередь отложенной агрегации
python -m pipeline.orchestrator.aggregate_streams --due

# пересчитать один стрим / все игры / только показать расхождения
python -m pipeline.orchestrator.aggregate_streams --stream 123
python -m pipeline.orchestrator.aggregate_streams --all
python -m pipeline.orchestrator.aggregate_streams --drift

# откатить батч истории или все применённые батчи стрима
python -m pipeline.orchestrator.rollback_stats --batch 42
python -m pipeline.orchestrator.rollback_stats --stream 123
```

### Дуэли

`duels`, `duels_franchises`, `duels_characters`, `duels_character_versions`,
`duels_abilities`, `duels_scenarios`, `duels_scenario_usage`,
`duels_version_abilities` — игровая механика дуэлей (модели и версии
персонажей, способности, сценарии).

### Telegram

| Таблица | Назначение |
|---|---|
| `telegram_announcements` | найденные посты-анонсы: chat/message id, снапшоты текста и entities, статус |
| `telegram_announcement_vods` | задача поиска VOD: stream/broadcast id, `stream_db_id`, `recording_id`, `check_at`, attempts, статус, applied/undo/restore; сам URL не хранится — только ссылка на `stream_recordings` |
| `telegram_post_edit_settings` | шаблон правки поста (header/item/separator/footer, delay) |
| `telegram_post_edit_operations` | журнал операций publish/undo/restore с before/after |

Подробности — `docs/TELEGRAM.md`.

## Миграции

Текущая история — `alembic/versions/0001…0020`:

- `0001` — начальная схема;
- `0002` — аббревиатуры жанров/платформ;
- `0003` — поля HLTB;
- `0004` — `stream_titles`;
- `0005` — флаги `bot_commands`;
- `0006` — `user_profiles`;
- `0007` — `duration_minutes` в stats и слияние дублей игр;
- `0008`–`0010` — Telegram-анонсы, custom emoji, ссылки;
- `0011` — `twitch_streamer_authorizations`;
- `0012` — post-stream editing;
- `0013` — restore после правки поста;
- `0014` — роли и permissions;
- `0015` — удаление plaintext Twitch-токенов;
- `0016` — удаление legacy `user_permissions`;
- `0017` — runtime-сессии, сэмплы, бакеты, очередь `stream_stats_jobs`, провенанс `game_stats`;
- `0018` — история изменений (`stats_change_batches`, `stats_change_log`);
- `0019` — чат, команды и присутствие (`chat_messages`, `command_usage_logs`, `stream_chat_participants`);
- `0020` — `stream_recordings` как единственный реестр VOD: `twitch_stream_id`/`twitch_video_id`/`is_available`, перенос ссылок из `telegram_announcement_vods` и связывание задач через `recording_id`.

Проверить текущую ревизию: `.venv\Scripts\python.exe -m alembic current`.
