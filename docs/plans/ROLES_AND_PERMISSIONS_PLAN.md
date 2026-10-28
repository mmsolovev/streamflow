# Система ролей и прав

Статус: реализация завершена в рабочей ветке, миграции ещё не применялись к
production-БД. Перед применением к существующей БД выполните seed ролей между
ревизиями `0014` и `0016`: сначала `alembic upgrade 0014`, затем
`python -m database.seed_roles --apply`, потом `alembic upgrade head`.
Перед последней командой задайте `TOKEN_ENCRYPTION_KEY`: ревизия `0015`
шифрует legacy-токены и только затем удаляет plaintext-колонки.
Область: бот (`core/`, `commands/`, `services/`), веб-бэкенд (`backend/`), БД и OAuth-токены.

## 1. Цель

Заменить разрозненные проверки по env-спискам (`ADMINS`, `ALLOWED_USERS`,
`RECOMMENDATIONS_BANNED_USERS`) и флаги `users.is_admin` / `is_streamer` /
`is_trusted` / `twitch_management` на единую модель ролей и ограничений.

Роли:

1. **Владелец** (`owner`) — один, `mishgan_sol`. Все действия. В интерфейсе
   отображается как администратор.
2. **Стример** (`streamer`) — основной канал, пока `Tabula`. Все действия,
   кроме назначения/снятия администраторов и стримеров. В интерфейсе
   отображается как администратор. В будущем возможно несколько стримеров.
3. **Администратор** (`admin`) — админ-команды, редактирование таблиц,
   назначение/снятие редакторов.
4. **Редактор** (`editor`) — редактирование таблиц.
5. **Пользователь** (`user`) — авторизованный пользователь, может предлагать
   игры от своего имени.
6. **Забанен на Twitch** — не роль, а ограничение: авторизация и чтение
   разрешены, изменения запрещены. На роли администраторов и редакторов не
   влияет.
7. **Забанен на сервисе** — отдельное ограничение: блокирует web-записи,
   не влияет на чтение и на доступность команд бота.

## 2. Принятые решения

- `mishgan_sol` — владелец. Twitch User ID: `137727939`. После перенумерации
  `users.id` = 1.
- `tabula` — стример. После перенумерации `users.id` = 2.
- Псевдопользователь `twitch` (релизы IGDB) сохраняется отдельно. После
  перенумерации `users.id` = 3. Старые занятые ID `1/2/3` перенесены на
  `6045/6046/6047`.
- `orfeylefontu` и все текущие пользователи из `ALLOWED_USERS`
  (`eternalchilll`, `wraith8`, `kampacha`, `angrys2l`) получают роль `editor`.
- `is_trusted` и `twitch_management` удаляются как рудименты.
- `is_admin` удаляется: источник истины — `users.role`.
- `is_streamer` не используется для авторизации: этот флаг сейчас означает
  Twitch-партнёра/аффилиата. Роль стримера хранится отдельно в `users.role`.
- Бан на Twitch не понижает роль администратора/редактора. Он блокирует только
  действия обычного пользователя.
- Service-бан управляется только владельцем, блокирует только web-записи,
  команды бота остаются доступными.
- При недоступности Twitch API считаем, что бана нет (fail-open). Если API
  вернул бан — сохраняем и применяем ограничение.
- Снятие администраторов/стримеров — только владелец. Стример и админ могут
  назначать и снимать только редакторов.
- Владельца нельзя снять или заблокировать через API. Роль владельца
  закрепляется за неизменяемым Twitch User ID.
- Деплоя ещё не было, production-сессий нет. Обратную совместимость формата
  сессий можно не сохранять, но миграции должны быть идемпотентными и
  обратимыми.

## 3. Матрица возможностей

| Возможность | owner | streamer | admin | editor | user | twitch-ban | service-ban |
|---|---|---|---|---|---|---|---|
| Чтение данных | + | + | + | + | + | + | + |
| Предложить игру | + | + | + | + | + | - | - |
| Редактировать таблицы | + | + | + | + | - | - | - |
| Админ-команды бота | + | + | + | - | - | - | + |
| Назначать/снимать редакторов | + | + | + | - | - | - | - |
| Назначать/снимать админов, стримеров | + | - | - | - | - | - | - |
| Управлять service-баном | + | - | - | - | - | - | - |

Примечания:

- Twitch-бан применяется только к роли `user`. Если пользователь — `editor`,
  `admin`, `streamer` или `owner`, его права не меняются.
- Service-бан не понижает роль, но блокирует write-операции в веб-API.
  Команды бота остаются доступны по роли; для `!рек` через бота service-бан
  действие не блокирует, а Twitch-бан блокирует. Владельца забанить нельзя.
- `owner` и `streamer` отдаются фронтенду с `display_role = "admin"`.

## 4. Целевая схема БД

### 4.1 `users.role`

- Тип: `String(20)` + CHECK-констрейнт
  (`owner`, `streamer`, `admin`, `editor`, `user`).
- `NOT NULL DEFAULT 'user'`.
- Индекс по `role` для админского списка.
- Владелец дополнительно защищён на уровне кода и аудита.

### 4.2 Ограничения

Таблица `user_restrictions`:

| Поле | Назначение |
|---|---|
| `id` | PK |
| `user_id` | FK → `users.id`, ON DELETE CASCADE |
| `kind` | `twitch_ban` / `service_ban` |
| `channel` | логин/ID канала для Twitch-бана, для service-бана NULL |
| `reason` | причина |
| `source` | `twitch_api` / `manual` |
| `created_by_user_id` | кто выдал ( для service-бана) |
| `created_at` | когда |
| `checked_at` | когда последний раз подтверждали (Twitch) |
| `expires_at` | когда истекает, если известно; иначе NULL |
| `lifted_at` | когда снят |

Частичный уникальный индекс: одна активная запись на пару
`(user_id, kind, channel)`.

### 4.3 Аудит

Таблица `moderation_audit`:

- `id`, `actor_user_id`, `target_user_id`, `action`
  (`role_changed`, `service_ban_created`, `service_ban_lifted`), `old_value`, `new_value`,
  `reason`, `created_at`, `ip`, `user_agent`.

### 4.4 Сессии и токены

`web_sessions`:

- `id` UUID остаётся внутренним PK.
- `token_hash` `String(64)`, unique, NOT NULL — SHA-256 от случайного
  session-токена.
- `csrf_hash` `String(64)` — хеш CSRF-токена, привязанного к сессии.
- `created_at`, `last_activity_at`, `expires_at`, `absolute_expires_at`.

`twitch_authorizations` и `twitch_streamer_authorizations`:

- `access_token_encrypted`, `refresh_token_encrypted` (Text, nullable на время
  миграции).
- `key_version` (Integer, default 1).
- После проверки миграции старые plaintext-колонки
  `access_token`/`refresh_token` удаляются.

### 4.5 Удаляемые колонки

- `users.is_admin`
- `users.is_trusted`
- `users.twitch_management`

`users.is_streamer` остаётся только как признак Twitch-партнёра/аффилиата и
не участвует в authz. При желании позже переименовать в
`twitch_broadcaster_type`.

## 5. Реализованный authz-слой

`services/authz_service.py` содержит:

- `Role`, `Capability`, матрицу `ROLE_CAPABILITIES` и иерархию
  `owner > streamer > admin > editor > user`;
- `can()` с учётом service- и Twitch-ограничений, `display_role()` и
  `Actor.can_write`;
- `resolve_actor()` по Twitch User ID с fallback по логину и process-local
  кэшем на 60 секунд для команд бота;
- `apply_owner_bootstrap()`: владелец восстанавливается по Twitch User ID,
  логин используется только как fallback.

`backend/deps.py` получает сессию по хешу cookie, проверяет CSRF для write-
методов, формирует `Actor` с активными ограничениями и предоставляет
`require_capability()`. Переходные `require_admin` и
`require_streamer_or_admin` оставлены как обёртки.

`/api/v1/auth/me` начинает возвращать:

```json
{
  "id": 1,
  "login": "mishgan_sol",
  "display_name": "Mishgan",
  "role": "owner",
  "display_role": "admin",
  "capabilities": ["recommend", "edit_tables", "admin_commands", "manage_editors", "manage_staff", "manage_service_ban"],
  "is_twitch_banned": false,
  "is_service_banned": false,
  "can_write": true
}
```

Поля `is_admin` и `is_streamer` остаются в ответе только для переходной
совместимости: `is_admin` вычисляется как
`role in ("owner", "streamer", "admin")`, `is_streamer` — как
`role == "streamer"`. Фронтенд использует `capabilities` и `can_write`.

## 6. Управление ролями

Новые endpoints:

- `GET /api/v1/admin/users` — поиск пользователей, роль, ограничения.
- `PATCH /api/v1/admin/users/{id}/role` — смена роли.
- `POST /api/v1/admin/users/{id}/restrictions` — service-бан.
- `DELETE /api/v1/admin/users/{id}/restrictions/{restriction_id}` — снятие
  service-бана.
- `GET /api/v1/admin/audit` — журнал изменений (owner).

Правила:

- `owner` может менять любую роль, кроме собственной.
- `streamer` и `admin` могут назначать/снимать только `editor`.
- Снять `admin`/`streamer` может только `owner`.
- Нельзя изменить роль owner: его защита проверяется до смены роли.
- Все операции требуют CSRF, пишутся в `moderation_audit`.
- При смене роли и выдаче service-бана все веб-сессии пользователя отзываются.

## 7. Twitch-бан

### 7.1 Проверка

- Добавить elevated-scope `moderator:read:banned_users` в
  `TWITCH_STREAMER_SCOPE` / env.
- Использовать Helix:
  `GET https://api.twitch.tv/helix/moderation/banned?broadcaster_id=<primary>&user_id=<user>`.
- Токен — «стримерский» токен основного канала (`Tabula`) из
  `twitch_streamer_authorizations`.
- Основной канал определяется через `RECOMMENDATIONS_STREAMER_LOGIN`, а его
  `twitch_user_id` — из БД. Жёсткий `45` не использовать.
- Ответ содержит записи — пользователь забанен. Пустой ответ — не забанен.

### 7.2 Когда проверять

- При OAuth-логине после создания/обновления пользователя.
- Лениво при обращении к API через process-local TTL
  `TWITCH_BAN_CHECK_TTL_SECONDS` (по умолчанию 600).
- Периодическая фоновая задача в `lifespan` для пользователей с активными
  сессиями (интервал `TWITCH_BAN_SYNC_INTERVAL_SECONDS`, по умолчанию 900).

### 7.3 Политика ошибок

- По умолчанию `TWITCH_BAN_FAIL_OPEN=true`: при ошибке API сохраняем последнее
  известное состояние, новых ограничений не добавляем.
- Если бан был подтверждён, а потом API недоступен — ограничение остаётся до
  успешной проверки или истечения `expires_at`.
- Бан на Twitch применяется только к роли `user`.
- Снятие бана на Twitch: при успешной проверке ставим `lifted_at` у активной
  записи `kind='twitch_ban'`.

## 8. Токены и сессии

### 8.1 Что хранить в env

В env остаются только секреты приложения:

- `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`, `TWITCH_REDIRECT_URI`;
- `TOKEN_ENCRYPTION_KEY` — base64 32-байтного ключа;
- `OWNER_TWITCH_USER_ID=137727939`, `OWNER_TWITCH_LOGIN=mishgan_sol`
  (bootstrap, не секрет);
- bot refresh token (`TWITCH_REFRESH_TOKEN`) — допустимо для текущего
  масштаба, но лучше Docker secret/secret manager.

Пользовательские refresh-токены в env не хранить: они per-user и ротируются.

### 8.2 Шифрование

- `cryptography` + Fernet (AES-128-CBC + HMAC) или AES-GCM.
- Добавить `cryptography` в `requirements.txt`.
- Шифровать `access_token` и `refresh_token` обеих таблиц авторизаций.
- Ключ: `TOKEN_ENCRYPTION_KEY` (env). Версия — `key_version`, чтобы позже
  поддержать ротацию ключей.
- Миграция: зашифровать существующие plaintext-токены, проверить чтение,
  только потом удалить plaintext-колонки.
- Токены никогда не логировать; в ошибках и аудите только `user_id`.

### 8.3 Web-сессии

- Cookie содержит случайный `secrets.token_urlsafe(32)`.
- В БД — только `SHA-256` токена.
- Cookie: `HttpOnly`, `Secure` в prod, `SameSite=Lax`, `Path=/`.
- Абсолютный TTL (`BACKEND_SESSION_TTL_DAYS`) + idle TTL.
- Отзыв всех сессий при смене роли, service-бане, выходе.
- CSRF-токен привязан к сессии и проверяется по хешу в `web_sessions`.
- При смене формата сессий старые сессии просто инвалидируются (деплоя ещё не
  было).

## 9. Команды бота

Проверки перевести на `services/authz_service.py`.

- `!отбой`, `!старт`, `!gpt`, `!рек --`, `!рек +` — `admin` и выше.
- `!фильм +`, `!фильм -`, `!фильм time` — `admin` и выше.
- `!таймер` (управление) — Twitch-модератор канала или `editor` и выше
  (текущий `ALLOWED_USERS` становится редакторами).
- `!рек` — `user` и выше; Twitch-бан блокирует действие.
- Команды бота проверяются через `Actor.can_command()` и не блокируются
  service-баном: он ограничивает только web-записи.
- Роль определяется по `chatter.id` (Twitch User ID), с fallback по логину.
- `ADMINS`, `ALLOWED_USERS`, `RECOMMENDATIONS_BANNED_USERS` удаляются из
  проверок. Использовать их только в одноразовом seed-скрипте.

## 10. Привязка к стримеру и `users.id`

### 10.1 Выполненная перенумерация `users.id`

Изначально план предполагал сохранить ID `44/45/46`, но перенумерация была
выполнена скриптом `database/remap_primary_user_ids.py`:

- `mishgan_sol`, `tabula` и псевдопользователь `twitch` получили
  `users.id = 1/2/3`;
- старые занятые ID `1/2/3` (`juice`, `pathofexilebota`, `goodboy_tv`)
  перенесены на `6045/6046/6047`;
- все FK обновлены, sequence сброшен на `6047`;
- владелец по-прежнему определяется по неизменяемому
  `twitch_user_id=137727939` (env `OWNER_TWITCH_USER_ID`), логин — fallback;
- основной стример определяется по `RECOMMENDATIONS_STREAMER_LOGIN=tabula`,
  его `users.id` резолвится из БД и кэшируется;
- `SHEETS_STREAMER_ID` / `BACKEND_STREAMER_ID` оставлены как необязательный
  override, жёсткой зависимости от числового ID нет;
- `backend/deps.get_streamer_id()` — async-зависимость, которая резолвит ID
  по логину основного стримера.

### 10.2 Несколько стримеров

Сейчас роль `streamer` — это staff-роль, а статистика по-прежнему привязана к
одному основному каналу. Несколько аккаунтов со ролью `streamer` можно будет
добавить без изменения схемы, но данные всё равно будут собираться по
основному каналу.

Полноценная мультистримерность — отдельный проект:

1. Таблица `streamers` (`user_id`, `twitch_channel_id`, `is_primary`).
2. `streamer_id` в `streams` и в runtime-сессиях.
3. Протянуть `streamer_id` через репозитории, Sheets, статистику и UI.
4. Выбор активного стримера в интерфейсе.

До этого оставить одного основного стримера, но без жёстких числовых ID.

## 11. Этапы реализации

### Этап 1. Миграции и seed

- [x] `0014_roles_permissions`: `users.role`, ограничения, аудит, безопасные
  сессии и encrypted-колонки токенов.
- [x] `database/seed_roles.py`: owner по Twitch ID, `tabula` → streamer,
  `orfeylefontu` и legacy `ALLOWED_USERS` → editor.
- [x] `0015_drop_plaintext_twitch_tokens`: перенос и Fernet-шифрование
  токенов внутри миграции, затем удаление plaintext-колонок.
- [x] `0016_drop_legacy_user_permissions`: удаление `is_trusted`,
  `twitch_management` и `is_admin`.
- [ ] Прогон миграций на копии production-БД и создание резервной копии перед
  применением.

### Этап 2. Authz-ядро

- [x] `services/authz_service.py` с ролями, capabilities, ограничениями и
  кэшем.
- [x] `backend/deps.py` и API используют `require_capability`.
- [x] `/auth/me` возвращает роль, отображаемую роль, capabilities, баны и
  `can_write`.
- [x] Автоматическое повышение по `ADMINS` при логине удалено.

### Этап 3. Токены и сессии

- [x] Добавлен `cryptography`; токены шифруются Fernet и расшифровываются
  только перед обращением к Twitch.
- [x] Cookie содержит случайный токен, в БД хранится SHA-256; CSRF привязан к
  конкретной сессии.
- [x] Сессии отзываются при смене роли и выдаче service-бана.
- [ ] Проверить round-trip и ротацию токенов на копии production-данных.

### Этап 4. Баны

- [x] `moderator:read:banned_users` добавлен в streamer OAuth scope.
- [x] Helix-проверка и кэш ограничений в `user_restrictions`.
- [x] Проверка при OAuth-логине, при API-запросах и фоновая синхронизация
  активных сессий.
- [x] Service-бан доступен только owner, блокирует web write-операции и
  записывается в аудит.
- [ ] Проверить scope и фактический ответ Helix на подключённом streamer-токене.

### Этап 5. API управления ролями

- [x] `backend/routers/admin.py`: список пользователей, смена роли,
  service-бан, снятие бана и аудит.
- [x] Pydantic-схемы и серверная проверка ролей.
- [x] Защита owner и отзыв сессий при смене роли/выдаче бана.

### Этап 6. Перевод существующих проверок

- [x] Роутеры игр, релизов, стримов, рекомендаций, HLTB и Telegram post-edit
  используют capabilities.
- [x] Команды бота используют `resolve_actor()` вместо env-списков.
- [x] `utils/permissions.py` оставлен совместимой тонкой обёрткой.
- [x] Основной стример резолвится по логину, без жёсткого числового ID.

### Этап 7. Тесты и документация

- [x] Существующий набор `unittest` проходит: 195 тестов.
- [x] Проходят компиляция backend, frontend typecheck и production build.
- [ ] Дополнить тесты матрицей всех ролей, owner-защитой, аудитом,
  шифрованием и ротацией токенов.
- [x] Обновлён `.env.example` и этот документ.

### Этап 8. Внедрение

Это единственный незавершённый этап. Выполнять в указанной последовательности:

1. Создать резервную копию БД и установить `TOKEN_ENCRYPTION_KEY`.
2. Применить `alembic upgrade 0014`.
3. Проверить вывод `python -m database.seed_roles`, затем применить
   `python -m database.seed_roles --apply`.
4. Применить `alembic upgrade head` (ревизии `0015` и `0016`).
5. Проверить вход и права owner, streamer, admin, editor и user, затем
   проверить Twitch- и service-бан.
6. Удалить legacy-переменные из production env после успешного seed.

## 12. Изменения env

Добавить:

```dotenv
OWNER_TWITCH_USER_ID=137727939
OWNER_TWITCH_LOGIN=mishgan_sol
TOKEN_ENCRYPTION_KEY=
TWITCH_BAN_CHECK_TTL_SECONDS=600
TWITCH_BAN_SYNC_INTERVAL_SECONDS=900
TWITCH_BAN_FAIL_OPEN=true
BACKEND_SESSION_IDLE_MINUTES=1440
TWITCH_STREAMER_SCOPE=channel:read:redemptions channel:manage:redemptions moderator:read:banned_users
```

Пометить устаревшими после seed:

- `ADMINS`
- `ALLOWED_USERS`
- `RECOMMENDATIONS_BANNED_USERS`

Оставить:

- `RECOMMENDATIONS_STREAMER_LOGIN=tabula`
- `RECOMMENDATIONS_STREAMER_DISPLAY_NAME=Tabula`
- `STREAMER_LOGINS` — только для bootstrap elevated OAuth, затем проверка по
  роли в БД.
- `SHEETS_STREAMER_ID` / `BACKEND_STREAMER_ID` — необязательный override.

## 13. Безопасность: чек-лист

- [x] Код шифрует OAuth-токены и после `0015` удаляет plaintext-колонки.
- [x] Session-токен и CSRF-токен хранятся в БД только в виде SHA-256.
- [x] CSRF проверяется для каждого небезопасного HTTP-метода.
- [x] Владелец защищён от изменения роли и service-бана через API.
- [x] Изменения ролей и service-банов пишутся в аудит.
- [x] Проверка прав выполняется на сервере; UI использует capabilities только
  для отображения доступных действий.
- [ ] Установить `BACKEND_COOKIE_SECURE=true` в production.
- [ ] Ограничить `BACKEND_CORS_ORIGINS` production-origin'ами.
- [ ] Проверить после миграции отсутствие plaintext-токенов в БД.
- [ ] Настроить rate limit для auth и write-endpoints при необходимости.

## 14. Риски

| Риск | Митигация |
|---|---|
| Рассинхрон env-списков и БД | env только для seed; источник истины — `users.role` |
| Потеря доступа владельца | owner закреплён по Twitch User ID, запрет снятия |
| Ошибка в миграции токенов | бэкап, encrypted-колонки рядом, проверка чтения, только потом drop |
| Twitch API недоступен | fail-open по умолчанию, последнее известное состояние сохраняется |
| Смена `users.id` ломает FK | не менять ID; резолвить по Twitch ID/логину |
| Несколько стримеров | отдельный этап с `streamers` и `streamer_id` в данных |
| Старые сессии после деплоя | инвалидировать все `web_sessions` миграцией |
