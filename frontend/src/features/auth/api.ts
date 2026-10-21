import { API_BASE_URL, api } from '@/api/client'
import type { StreamerAuthStatus, UserView } from '@/api/types'
import { ApiError } from '@/lib/apiError'

/** Текущий пользователь или `null`, если сессии нет (401). */
export async function getCurrentUser(): Promise<UserView | null> {
  try {
    const { data } = await api.get<UserView>('/auth/me')
    return data
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null
    throw error
  }
}

/** Полный переход браузера на OAuth-вход Twitch (не fetch). */
export function goToLogin(): void {
  window.location.assign(`${API_BASE_URL}/auth/login`)
}

/**
 * Полный переход браузера на OAuth-вход Twitch с расширенными правами
 * (стримерский токен). Доступен не всем аккаунтам.
 */
export function goToStreamerLogin(): void {
  window.location.assign(`${API_BASE_URL}/auth/streamer/login`)
}

/** Статус «стримерских» токенов (только для админов). */
export async function getStreamerStatus(): Promise<StreamerAuthStatus> {
  const { data } = await api.get<StreamerAuthStatus>('/auth/streamer/status')
  return data
}

export async function logout(): Promise<void> {
  await api.post('/auth/logout')
}
