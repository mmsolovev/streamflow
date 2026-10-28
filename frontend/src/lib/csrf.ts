const CSRF_COOKIE_NAME = 'backend_csrf_token'

/**
 * Читает CSRF-токен из cookie (double-submit). Cookie не HttpOnly,
 * поэтому доступна из JS. Токен не храним в памяти — всегда читаем свежий.
 */
export function readCsrfToken(): string | null {
  const prefix = `${CSRF_COOKIE_NAME}=`
  const entry = document.cookie.split('; ').find((cookie) => cookie.startsWith(prefix))
  if (!entry) return null
  return decodeURIComponent(entry.slice(prefix.length))
}
