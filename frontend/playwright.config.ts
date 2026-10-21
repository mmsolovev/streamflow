import { defineConfig } from '@playwright/test'

/**
 * Смоук-тесты фронтенда.
 *
 * Используем установленный системный Chrome (`channel: 'chrome'`), поэтому
 * браузеры Playwright скачивать не нужно.
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 30_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  reporter: [['list']],
  use: {
    baseURL: 'http://localhost:5173',
    channel: 'chrome',
    viewport: { width: 1280, height: 900 },
    locale: 'ru-RU',
  },
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: true,
    timeout: 60_000,
  },
})
