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
| `game_stats` | агрегаты по игре: минуты, средние/пиковые зрители, число стримов, последний стрим |
| `streams` | стримы: `external_id` (unique), title, `started_at`, `ended_at`, `duration_minutes`, viewers, followers/views gained |
| `stream_titles` | история смены названий стрима |
| `stream_games` | игры внутри стрима: порядок, интервал, минуты, зрители, подписчики |
| `stream_recordings` | ссылки на записи/VOD (`source`, `url`, `duration_minutes`) |
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
| `chat_messages` | сообщения чата (если включён сбор) |

`users.role` ограничен CHECK-ом: `owner`, `streamer`, `admin`, `editor`,
`user`. Роли и capability описаны в `services/authz_service.py`.

### Команды и контент

| Таблица | Назначение |
|---|---|
| `bot_commands` | реестр команд: name, description, `is_visible`, `is_active`, `bot_name` |
| `bot_command_aliases` | алиасы команд |
| `command_usage_logs` | статистика использования команд |
| `calendar_days` | календарные даты (`day`, `month`, `day_of_year`) |
| `holidays` | праздники, привязанные к `calendar_days`; заполняются `database/sync_holidays.py` из `storage/holidays.json` |
| `famous_persons` | известные люди, привязанные к `calendar_days` |
| `clips`, `clip_tags` | клипы и теги |

### Runtime live-метрики

| Таблица | Назначение |
|---|---|
| `stream_runtime_samples` | сырые сэмплы: `sampled_at`, viewers, followers, title, category |
| `stream_runtime_buckets` | агрегаты по интервалам: `bucket_start/end`, avg/max viewers, followers gained |

Сборщик — `runtime/collector.py`, интервал — `STREAM_RUNTIME_SAMPLE_SECONDS`
(по умолчанию 60 с). Сейчас сессии и агрегаты сохраняются в JSON
(`storage/runtime/active_stream_session.json`,
`completed_stream_sessions.json`); таблицы `stream_runtime_samples` и
`stream_runtime_buckets` существуют в схеме, но коллектор их не заполняет.
Агрегация — `runtime/metrics.py`.

### Дуэли

`duels`, `duels_franchises`, `duels_characters`, `duels_character_versions`,
`duels_abilities`, `duels_scenarios`, `duels_scenario_usage`,
`duels_version_abilities` — игровая механика дуэлей (модели и версии
персонажей, способности, сценарии).

### Telegram

| Таблица | Назначение |
|---|---|
| `telegram_announcements` | найденные посты-анонсы: chat/message id, снапшоты текста и entities, статус |
| `telegram_announcement_vods` | задача поиска VOD: stream, `check_at`, attempts, статус, applied/undo/restore |
| `telegram_post_edit_settings` | шаблон правки поста (header/item/separator/footer, delay) |
| `telegram_post_edit_operations` | журнал операций publish/undo/restore с before/after |

Подробности — `docs/TELEGRAM.md`.

## Миграции

Текущая история — `alembic/versions/0001…0016`:

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
- `0016` — удаление legacy `user_permissions`.

Проверить текущую ревизию: `.venv\Scripts\python.exe -m alembic current`.
