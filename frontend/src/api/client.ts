import axios from 'axios'

import { toApiError } from '@/lib/apiError'
import { readCsrfToken } from '@/lib/csrf'

const SAFE_METHODS = new Set(['get', 'head', 'options'])

/** Базовый URL API. По умолчанию относительный — через прокси Vite. */
export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? '/api/v1'

/**
 * Единый axios-клиент.
 * - `withCredentials` — чтобы отправлялись cookie сессии;
 * - для небезопасных методов подставляет заголовок `X-CSRF-Token` из cookie;
 * - все ошибки приводятся к `ApiError`.
 */
export const api = axios.create({
  baseURL: API_BASE_URL,
  withCredentials: true,
  headers: { Accept: 'application/json' },
  paramsSerializer: {
    /**
     * Массивы отправляем повторяющимся параметром без скобок:
     * `filters=a&filters=b`. По умолчанию axios ставит `filters[]=a`,
     * а FastAPI такой параметр не видит — фильтры молча игнорируются.
     */
    serialize(params: Record<string, unknown>) {
      const search = new URLSearchParams()
      for (const [key, value] of Object.entries(params)) {
        if (value === undefined || value === null) continue
        if (Array.isArray(value)) {
          for (const item of value) search.append(key, String(item))
        } else {
          search.append(key, String(value))
        }
      }
      return search.toString()
    },
  },
})

api.interceptors.request.use((config) => {
  const method = (config.method ?? 'get').toLowerCase()
  if (!SAFE_METHODS.has(method)) {
    const token = readCsrfToken()
    if (token) config.headers.set('X-CSRF-Token', token)
  }
  return config
})

api.interceptors.response.use(
  (response) => response,
  (error: unknown) => Promise.reject(toApiError(error)),
)
