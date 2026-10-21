/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Базовый URL API. По умолчанию `/api/v1` (через прокси Vite). */
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
