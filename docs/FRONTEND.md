# Фронтенд

`frontend/` — React 19 + TypeScript + Vite + Tailwind CSS 4. Данные — из
`/api/v1` через axios, состояние сервера — TanStack Query, роутинг —
React Router v7.

## Запуск и проверки

```powershell
cd frontend
npm install
npm run dev        # http://localhost:5173
npm run build      # tsc -b && vite build
npm run lint       # oxlint
npm run typecheck  # tsc -b
npm test           # vitest run (только src/**/*.test.ts)
npm run test:e2e   # playwright
npm run gen:api    # OpenAPI -> src/api/schema.d.ts
```

Vite проксирует `/api` на `http://127.0.0.1:8001`; путь API по умолчанию —
`/api/v1` (`VITE_API_BASE_URL`). Запросы идут с `withCredentials: true`.

## Структура

```
src/
  api/          axios-клиент, CSRF, пагинация, сгенерированные OpenAPI-типы
  app/          QueryClient
  components/
    entity/     таблицы/ячейки сущностей (игры, стримы, участники, теги)
    layout/     TopBar, SectionBar, SectionPanel, AdminPanel
    ui/         кнопки, фильтры, пагинация, скелетоны, диалоги
  config/       nav.ts, socials.ts
  features/     games, streams, releases, recommendations, hltb, auth, meta,
                telegramPostEdit — api + hooks + view
  hooks/        useOffset, useTableSort, useDebouncedValue, useFocusGameRow
  lib/          format, tags, recommenders, games, csrf, apiError, cn
  pages/        StatsPage, GameDetailPage, AdminPage, PlaceholderPage
  styles/       подключение шрифтов
  types/        прикладные типы
e2e/            Playwright
```

Правило: сетевые вызовы — в `features/*/api.ts`, React Query — в
`features/*/use*.ts`, презентация — в `*View.tsx`/`*Table.tsx`, общие
компоненты — в `components/`.

## Роуты

| Путь | Компонент | Статус |
|---|---|---|
| `/` | `Navigate → /games` | |
| `/stats/*` | `Navigate → /games` | legacy-редирект |
| `/games` | `StatsPage section="games"` | готово |
| `/games/:gameId` | `GameDetailPage` | готово |
| `/streams` | `StatsPage section="streams"` | готово |
| `/releases` | `StatsPage section="releases"` | готово |
| `/recommendations` | `StatsPage section="recommendations"` | готово |
| `/hltb` | `StatsPage section="hltb"` | готово |
| `/commands` | `PlaceholderPage` | заглушка |
| `/events` | `PlaceholderPage` | заглушка |
| `/interactive` | `PlaceholderPage` | заглушка |
| `/admin` | `ProtectedRoute → /admin/management` | admin |
| `/admin/management` | `AdminPage section="management"` | admin |
| `/admin/connections` | `AdminPage section="connections"` | admin |
| `/admin/telegram` | `AdminPage section="telegram"` | admin |
| `*` | `NotFoundPage` | |

Навигация описана в `src/config/nav.ts`: вкладка «Статистика» включена,
«Команды»/«Ивенты»/«Интерактив» выключены. Разделы статистики:
`games`, `streams`, `releases`, `recommendations`, `hltb`. Админ-разделы:
`management`, `connections`, `telegram`; Telegram-подразделы — `start`,
`during`, `end` (по умолчанию `end`).

`ProtectedRoute requireAdmin` проверяет `is_admin`/capabilities из
`/auth/me`; при отсутствии сессии отправляет на Twitch OAuth.

## API-клиент

`src/api/client.ts`:

- базовый URL — `VITE_API_BASE_URL` или `/api/v1`;
- для `POST/PATCH/PUT/DELETE` подставляет `X-CSRF-Token` из cookie
  `backend_csrf_token`;
- массивы сериализует как `filters=a&filters=b` (FastAPI не понимает `[]`);
- ошибки приводит к `ApiError` (`src/lib/apiError.ts`).

Типы ответов генерируются из OpenAPI в `src/api/schema.d.ts`
(`npm run gen:api`); файл не редактировать вручную.

## Дизайн-токены

Шрифты: `Montserrat` (`--font-sans`) и `Orbitron` (`--font-social`, только
соцкнопки).

Базовая палитра (`:root` в `src/index.css`):

| Токен | Значение |
|---|---|
| `--topbar-bg` | `#282828` |
| `--page-bg` | `#15161a` |
| `--section-bg` | `#1b1c21` |
| `--card-bg` | `#222329` |
| `--text` | `#e8eaed` |
| `--text-muted` | `#9aa0a6` |
| `--accent` | `#9aa0a6` |

Палитра разделов задаётся через `data-section`:

| Раздел | Accent | Section bg | Card bg |
|---|---|---|---|
| `games` | `#55c366` | `#1a1f1d` | `#222927` |
| `streams` | `#9152f8` | `#1f1f23` | `#26262c` |
| `releases` | `#eb9f35` | `#1f1a17` | `#2a231f` |
| `recommendations` | `#5bbdf4` | `#171c22` | `#1f262e` |
| `admin` | `#7f8ea3` | `#1a1c21` | `#23262d` |
| `hltb` | `#bf1313` | `#1c1b1b` | `#292525` |
| `telegram` | `#2aabee` | `#171d21` | `#242d33` |

Новые цвета/отступы добавляй токенами в `index.css`, а не хардкодом в
компонентах. Для классов используется `cn()` (`clsx` + `tailwind-merge`).

## Тесты

- `npm test` — Vitest, окружение `node`, только чистые функции/модули из
  `src/**/*.test.ts`.
- `npm run test:e2e` — Playwright, конфиг в `frontend/playwright.config.*`.
- Перед коммитом: `npm run lint`, `npm run typecheck`, `npm test`.
