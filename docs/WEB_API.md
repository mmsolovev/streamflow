# Web API (FastAPI backend)

Руководство для разработки фронтенда. Бэкенд — пакет `backend/`, точка входа
`backend.main:app`.

- Базовый префикс: `/api/v1`
- Swagger UI: `GET /docs`
- OpenAPI-схема: `GET /openapi.json`
- ReDoc: `GET /redoc`

## Запуск локально

```bash
.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8001
# http://127.0.0.1:8001/docs
```

Фронтенд в `WebStorm` запускается на своём порту (например,
`http://localhost:5173`) и обращается к `http://127.0.0.1:8001`.

## CORS и cookie

Задайте origin фронтенда в `.env` (через запятую), иначе браузер заблокирует
запросы:

```
BACKEND_CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
BACKEND_COOKIE_SECURE=false
```

Требования к фронтенду:

- каждый запрос — с `credentials: "include"` (fetch) / `withCredentials: true`
  (axios), чтобы отправлялись cookie;
- сервер отвечает `Access-Control-Allow-Credentials: true` и конкретными
  origin (не `*`) — уже настроено.

Имена cookie (настраиваются, значения по умолчанию):

| Cookie | HttpOnly | Назначение |
|---|---|---|
| `backend_session_id` | да | идентификатор web-сессии (UUID) |
| `backend_csrf_token` | нет | CSRF-токен (double-submit) |
| `backend_oauth_state` | да | одноразовый `state` во время OAuth |

`SameSite=Lax`. Если фронт и API на одном сайте (например, `app.example.com` и
`api.example.com`, либо один домен через reverse-proxy) — cookie отправляются
корректно. На production включите `BACKEND_COOKIE_SECURE=true` и работайте по
HTTPS.

## Аутентификация (Twitch OAuth)

Cookie-сессии, токен хранить на фронте не нужно.

1. Пользователь нажимает «Войти». Фронтенд делает **навигацию** (полный переход
   браузера, не fetch) на:

   ```
   GET /api/v1/auth/login
   ```

   Сервер ставит cookie `backend_oauth_state` и отвечает `307` редиректом на
   Twitch. Если OAuth не настроен — `503 {detail:{code:"oauth_not_configured"}}`.

2. Twitch возвращает пользователя на `TWITCH_REDIRECT_URI`
   (`/api/v1/auth/callback`). Сервер проверяет `state`, обменивает код,
   создаёт сессию и cookie.

   - Если задан `BACKEND_FRONTEND_URL`, сервер отвечает `303` редиректом на
     `BACKEND_FRONTEND_URL?login=success`. Это основной режим для сайта.
   - Если `BACKEND_FRONTEND_URL` пуст, возвращается JSON `UserView`.

3. Фронтенд после возврата читает текущего пользователя:

   ```
   GET /api/v1/auth/me
   ```

   `200 UserView` если сессия валидна, `401 {detail:{code:"unauthorized"}}` если нет.

Выход:

```
POST /api/v1/auth/logout   -> 204
```

Удаляет серверную сессию и cookie. Для POST нужен CSRF-заголовок (см. ниже).

`UserView`:

```json
{ "id": 45, "login": "tabula", "display_name": "Tabula",
  "is_streamer": true, "is_admin": false }
```

## CSRF

Для **небезопасных** методов (`POST`, `PATCH`, `DELETE`) нужен заголовок,
совпадающий с cookie `backend_csrf_token`:

```
X-CSRF-Token: <значение cookie backend_csrf_token>
```

Cookie не HttpOnly, поэтому JS может её прочитать. При `403` с
`{detail:{code:"csrf_failed"}}` — обновите токен (повторите вход либо
перечитайте cookie). Для `GET`/`HEAD`/`OPTIONS` CSRF не требуется.

## Формат ответов

Успешные списки — обёртка пагинации:

```json
{ "items": [ ... ], "total": 123, "limit": 100, "offset": 0 }
```

Параметры: `limit` (1..500, по умолчанию 100), `offset` (>=0).

Ошибки — единый конверт:

```json
{ "detail": { "code": "unauthorized", "message": "Требуется авторизация." } }
```

Коды, на которые стоит реагировать: `unauthorized` (401), `forbidden` (403),
`csrf_failed` (403), `not_found` (404), `validation_error` (422),
`oauth_not_configured` (503).

## Эндпоинты

### Публичные (без входа)

| Метод | Путь | Назначение |
|---|---|---|
| GET | `/api/v1/health` | healthcheck, `{status, database}` |
| GET | `/api/v1/games?limit&offset` | список игр (лист «ИГРЫ») |
| GET | `/api/v1/games/search?q=` | поиск игры по названию |
| GET | `/api/v1/games/{game_id}` | детали игры (+`genres`, `platforms`, `slug`) |
| GET | `/api/v1/streams?limit&offset&date&from&to` | список стримов (лист «СТРИМЫ») |
| GET | `/api/v1/streams/{stream_id}` | один стрим |
| GET | `/api/v1/releases?limit&offset` | ожидаемые релизы (лист «РЕЛИЗЫ») |
| GET | `/api/v1/recommendations?limit&offset` | рекомендованные игры (лист «СОВЕТЫ») |
| GET | `/api/v1/meta/genres` | справочник жанров (для фильтров) |
| GET | `/api/v1/meta/platforms` | справочник платформ (для фильтров) |
| GET | `/api/v1/auth/login` | старт OAuth (навигация) |
| GET | `/api/v1/auth/callback` | OAuth callback (обрабатывает Twitch) |
| GET | `/api/v1/auth/me` | текущий пользователь |

### Требуют входа (+ CSRF для не-GET)

| Метод | Путь | Роль | Тело | Ответ |
|---|---|---|---|---|
| PATCH | `/api/v1/games/{game_id}/streamer-state` | streamer/admin | `{liked: bool, completed: bool}` | `{game_id, liked, completed}` |
| PATCH | `/api/v1/releases/{game_id}/interested` | streamer/admin | `{interested: bool}` | `{game_id, interested}` |
| POST | `/api/v1/recommendations` | любой вошедший | `{query: str}` | `{outcome, message, recommendation}` |
| DELETE | `/api/v1/recommendations/{game_id}` | любой вошедший | — | `{outcome, message}` |
| POST | `/api/v1/auth/logout` | любой вошедший | — | `204` |

`outcome` у рекомендаций: `voted`, `added`, `already_streamed` (409),
`not_found` (404), `invalid` (422), `forbidden` (403).

### Фильтры стримов

- `date=YYYY-MM-DD` — конкретный день;
- `from=...&to=...` — окно (ISO, `to` включительно).

## Форматы полей

- Даты/время — ISO 8601, **naive UTC** (`2026-01-07T18:30:00`), как в БД и
  Sheets. Приводите к локальному времени на фронте.
- `tags` (стримы — массив; игры/релизы — готовая строка) и `recommenders` —
  предформатированные значения для отображения «как в таблице».
- `hours`/`duration_hours` — часы с одним знаком после запятой;
  `duration_minutes` — целые минуты.

## Пример (fetch)

```js
const API = "http://127.0.0.1:8001/api/v1";

async function currentUser() {
  const r = await fetch(`${API}/auth/me`, { credentials: "include" });
  if (r.status === 401) return null;
  if (!r.ok) throw new Error("auth failed");
  return r.json();
}

function csrfToken() {
  return document.cookie
    .split("; ")
    .find((c) => c.startsWith("backend_csrf_token="))
    ?.split("=")[1];
}

async function setLiked(gameId, liked, completed) {
  const r = await fetch(`${API}/games/${gameId}/streamer-state`, {
    method: "PATCH",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      "X-CSRF-Token": csrfToken(),
    },
    body: JSON.stringify({ liked, completed }),
  });
  if (!r.ok) throw new Error((await r.json()).detail?.code ?? "error");
  return r.json();
}

// вход: полный переход браузера, не fetch
// window.location.href = `${API}/auth/login`;
```

## Настройки, важные для фронта (`.env`)

```
BACKEND_CORS_ORIGINS=http://localhost:5173
BACKEND_FRONTEND_URL=http://localhost:5173/
BACKEND_COOKIE_SECURE=false
TWITCH_REDIRECT_URI=http://127.0.0.1:8001/api/v1/auth/callback
```

Для сайта на домене: `BACKEND_FRONTEND_URL=https://<домен>/`,
`BACKEND_COOKIE_SECURE=true`, `TWITCH_REDIRECT_URI=https://<домен>/api/v1/auth/callback`,
и этот же URI зарегистрирован в Twitch Application.

Полный список настроек — в [.env.example](../.env.example). Общий план бэкенда —
в [WEB_BACKEND_FASTAPI_ANALYSIS.md](WEB_BACKEND_FASTAPI_ANALYSIS.md).
