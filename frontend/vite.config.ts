import { fileURLToPath } from 'node:url'

import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    // На Windows HMR-сканер иногда не замечает правки (особенно после
    // замены файла целиком) — страница остаётся на старой версии модуля.
    // Опрос файловой системы надёжнее нативных событий.
    watch: {
      usePolling: true,
    },
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8001',
        changeOrigin: true,
      },
    },
  },
  test: {
    // Юнит-тесты — только в `src/`, e2e-сценарии живут в `e2e/` (Playwright).
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
    environment: 'node',
  },
})
