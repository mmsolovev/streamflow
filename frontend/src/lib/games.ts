/** Путь к картинке-заглушке (в `public/images/`, можно заменить своей). */
export const GAME_COVER_PLACEHOLDER = '/images/game-placeholder.svg'

/** Ключ сопоставления названий игр (устойчив к регистру и пробелам). */
export function normalizeGameName(name: string): string {
  return name.trim().toLowerCase()
}

/** Минимум данных игры, нужный для кликабельных обложек. */
export interface GameRef {
  id: number
  coverUrl: string | null
}
