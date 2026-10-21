# Фронтенд streamflow

Веб-интерфейс статистики стримов: разделы «Игры», «Стримы», «Релизы»,
«Советы», «HowLongToBeat», страница игры и админка.

Подробное описание архитектуры и плана работ — в
[`docs/WEB_FRONTEND_PLAN.md`](../docs/WEB_FRONTEND_PLAN.md).

## Стек

- React 19 + TypeScript + Vite
- React Router v7, TanStack Query v5, axios
- Tailwind CSS v4 (токены тем — в `src/index.css`), lucide-react, sonner
- Vitest (юнит-тесты) + Playwright (смоук-сценарии)

## Запуск

Нужен запущенный бэкенд на `http://127.0.0.1:8001` (см. раздел 11.1
`docs/WEB_FRONTEND_PLAN.md`).

```bash
npm install
npm run dev        # http://localhost:5173/
```

Vite проксирует `/api` на `127.0.0.1:8001`, поэтому cookie-сессия и CSRF
работают как на одном origin.

## Команды

| Команда | Что делает |
|---|---|
| `npm run dev` | dev-сервер с HMR |
| `npm run build` | проверка типов + сборка в `dist/` |
| `npm run typecheck` | `tsc -b` — проверка типов |
| `npm run lint` | oxlint |
| `npm run format` | prettier по всему проекту |
| `npm test` | юнит-тесты (Vitest) |
| `npm run test:e2e` | смоук-сценарии (Playwright, системный Chrome) |
| `npm run gen:api` | перегенерация `src/api/schema.d.ts` с запущенного бэкенда |

## Структура

```
src/
  api/         axios-клиент, типы из OpenAPI, схема (генерируется)
  app/         провайдеры (QueryClient)
  components/  entity/ (таблицы и ячейки), layout/ (каркас), ui/ (UI-кит)
  config/      навигация и соцсети
  features/    games, streams, releases, recommendations, hltb, auth, meta
  hooks/       useOffset, useTableSort, useDebouncedValue, useFocusGameRow
  lib/         форматтеры, теги, рекомендовавшие, CSRF, ошибки API
  pages/       StatsPage, GameDetailPage, AdminPage, PlaceholderPage
  styles/      шрифты (Montserrat, Orbitron)
e2e/           смоук-сценарии Playwright
```

## Локальные файлы (в Git не попадают)

- `.env.local` — при необходимости `VITE_API_BASE_URL` (по умолчанию `/api/v1`).
- `node_modules/`, `dist/`, `test-results/` — служебные, в `.gitignore`.
- `src/api/schema.d.ts` генерируется командой `npm run gen:api` (в репозитории
  тоже лежит, чтобы типы были без работающего бэкенда).
