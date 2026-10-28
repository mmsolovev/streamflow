# HTTP API

`FastAPI`-приложение в `backend/`, точка входа `backend.main:app`.

- База: `/api/v1` (`BACKEND_API_PREFIX`, по умолчанию `/api/v1`).
- Swagger UI: `/docs`, OpenAPI: `/openapi.json`, ReDoc: `/redoc`.
- Локальный запуск:

```powershell
.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8001
```

## Авторизация

Twitch OAuth + серверные cookie-сессии. Токены на фронтенде не хранятся.

| Cookie | HttpOnly | Назначение |
|---|---|---|
| `backend_session_id` | да | id web-сессии |
| `backend_csrf_token` | нет | CSRF-токен (double-submit) |
| `backend_oauth_state` | да | одноразовый OAuth `state` |

- `GET /auth/login` → `307` на Twitch. Если OAuth не настроен — `503`.
- `GET /auth/callback` проверяет `state`, создаёт сессию и делает `303` на
  `BACKEND_FRONTEND_URL?login=success`, если URL задан; иначе JSON `UserView`.
- `GET /auth/me` → `UserView` или `401`.
- `POST /auth/logout` → `204`.
- `GET /auth/streamer/status` — статус расширенного стримерского токена.

`UserView`: `id`, `login`, `display_name`, `role`, `capabilities`,
`is_streamer`, `is_admin`, `restrictions` (точный набор полей — в
`backend/schemas/auth.py`).

Для `POST` / `PATCH` / `PUT` / `DELETE` нужен заголовок:

```
X-CSRF-Token: <cookie backend_csrf_token>
```

Cookie `SameSite=Lax`, `BACKEND_COOKIE_SECURE=true` на production HTTPS.
CORS задаётся `BACKEND_CORS_ORIGINS` (конкретные origin, credentials включены).

## Форматы

Списки — `Page`:

```json
{"items": [], "total": 0, "total_all": 0, "aggregates": {}, "limit": 100, "offset": 0}
```

`limit` — 1..500 (по умолчанию 100), `offset` >= 0. Некоторые списки
дополнительно отдают `total_all` и `aggregates`.

Ошибки — единый конверт:

```json
{"detail": {"code": "not_found", "message": "Игра не найдена."}}
```

Коды: `unauthorized` (401), `forbidden` (403), `csrf_failed` (403),
`not_found` (404), `validation_error` (422), `oauth_not_configured` (503),
`error` (прочие HTTP-ошибки).

Даты/время — ISO 8601 naive UTC (`2026-01-07T18:30:00`). Локальное время —
на фронтенде. `hours`/`duration_hours` — часы с одним знаком после запятой,
`duration_minutes` — целые минуты.

## Публичные эндпоинты

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/health` | `{status, database}` |
| GET | `/games` | список игр |
| GET | `/games/covers` | обложки |
| GET | `/games/filters` | фильтры игр |
| GET | `/games/search?q=` | поиск игры |
| GET | `/games/{game_id}` | детали игры |
| GET | `/games/{game_id}/streams` | стримы с игрой |
| GET | `/streams` | список стримов (`date`, `from`, `to`, фильтры) |
| GET | `/streams/filters` | фильтры стримов |
| GET | `/streams/{stream_id}` | один стрим |
| GET | `/releases` | ожидаемые релизы |
| GET | `/releases/filters` | фильтры релизов |
| GET | `/recommendations` | рекомендации |
| GET | `/recommendations/filters` | фильтры рекомендаций |
| GET | `/recommendations/search` | поиск игры для рекомендации |
| GET | `/hltb` | игры с HLTB-данными |
| GET | `/meta/channel` | информация о канале |
| GET | `/meta/genres`, `/meta/platforms` | справочники |
| GET | `/users/search?q=` | поиск пользователей |
| GET | `/auth/login`, `/auth/callback`, `/auth/me` | OAuth |

## Запись (нужна сессия + CSRF)

| Метод | Путь | Доступ | Тело |
|---|---|---|---|
| PATCH | `/games/{game_id}/streamer-state` | `EDIT_TABLES` | `{liked: bool, completed: bool}` |
| PATCH | `/releases/{game_id}/interested` | `EDIT_TABLES` | `{interested: bool}` |
| POST | `/streams/{stream_id}/participants` | streamer/admin | `{user_login: str}` |
| DELETE | `/streams/{stream_id}/participants/{user_id}` | streamer/admin | — |
| POST | `/recommendations` | `RECOMMEND` | `{query: str}` |
| DELETE | `/recommendations/{game_id}` | `RECOMMEND` | — |
| POST | `/hltb/lookup` | `EDIT_TABLES` | `{url: str}` |
| POST | `/hltb` | `EDIT_TABLES` | `{url: str, game_id?: int}` |
| POST | `/auth/logout` | любой вошедший | — |

`POST /recommendations` возвращает `outcome`: `created`, `voted`,
`duplicate_vote`, `already_streamed` (409), `not_found` (404),
`invalid` (422), `forbidden` (403). Забаненный пользователь получает
имитацию успеха без записи.

## Администрирование

| Метод | Путь | Capability |
|---|---|---|
| GET | `/admin/users` | `MANAGE_EDITORS` |
| PATCH | `/admin/users/{user_id}/role` | `MANAGE_EDITORS`; staff-роли меняет только `owner` |
| GET | `/admin/audit` | `MANAGE_SERVICE_BAN` |
| POST | `/admin/users/{user_id}/restrictions` | `MANAGE_SERVICE_BAN` |
| DELETE | `/admin/users/{user_id}/restrictions/{restriction_id}` | `MANAGE_SERVICE_BAN` |

`MANAGE_EDITORS` позволяет менять только роли `editor`/`user`; роли
`streamer`/`admin` и владельца меняет только `owner` (роль владельца
защищена). После смены роли сессии пользователя отзываются.

## Telegram post-stream

Префикс `/admin/telegram/post-stream`, доступ — `EDIT_TABLES` (editor и выше):

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/` | состояние выбранного стрима/поста и настройки |
| PUT | `/target` | выбрать стрим/анонс |
| PATCH | `/settings` | изменить шаблон правки |
| POST | `/settings/reset` | сбросить шаблон |
| POST | `/publish` | опубликовать правку |
| POST | `/undo` | отменить правку |
| POST | `/restore` | восстановить исходный текст |
| POST | `/check-vod` | принудительно проверить VOD |

## Пример (axios)

```ts
const api = axios.create({
  baseURL: "/api/v1",
  withCredentials: true,
  headers: { "X-CSRF-Token": readCookie("backend_csrf_token") ?? "" },
});

const me = await api.get("/auth/me");
const games = await api.get("/games", { params: { limit: 50, offset: 0 } });
```

Фронтенд использует Vite proxy `/api` → `http://127.0.0.1:8001`.
Типы генерируются командой `npm run gen:api` в
`frontend/src/api/schema.d.ts`.
