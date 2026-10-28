import type { RecommendationView, ReleaseView } from '@/api/types'

/** Строка рекомендующего из API (совпадает у Релизов и Советов). */
export interface RecommenderEntry {
  user_login?: string | null
  display_name?: string | null
  recommendation_note?: string | null
}

type WithRecommenders = Pick<ReleaseView | RecommendationView, 'recommenders_list'>

/** Ключ фильтра по рекомендовавшему. */
export function recKey(login: string): string {
  return `rec:${login}`
}

/** Логин рекомендовавшего в нижнем регистре. */
export function recLogin(entry: RecommenderEntry): string {
  return (entry.user_login ?? '').trim().toLowerCase()
}

/** Отображаемая подпись: спец-псевдопользователи, иначе display_name/login. */
export function recommenderLabel(entry: RecommenderEntry): string {
  const login = recLogin(entry)
  if (login === 'tabula') return 'Tabula'
  if (login === 'twitch') return 'Twitch'
  return entry.display_name || entry.user_login || ''
}

/**
 * Порядок чипов: Tabula, Twitch, затем остальные по алфавиту.
 */
export function sortRecommenderEntries(entries: RecommenderEntry[]): RecommenderEntry[] {
  const rank = (entry: RecommenderEntry): number => {
    const login = recLogin(entry)
    if (login === 'tabula') return 0
    if (login === 'twitch') return 1
    return 2
  }
  return [...entries].sort((a, b) => {
    const diff = rank(a) - rank(b)
    if (diff !== 0) return diff
    return recommenderLabel(a).localeCompare(recommenderLabel(b), 'ru')
  })
}

/** Есть ли рекомендация от данного логина в строке. */
export function hasRecommender(
  item: WithRecommenders,
  login: string | null | undefined,
): boolean {
  if (!login) return false
  const target = login.trim().toLowerCase()
  return item.recommenders_list.some((entry) => recLogin(entry) === target)
}

/** Подсказка для скрытых чипов «ещё»: «Имя: заметка» по каждому. */
export function recommendersTooltip(entries: RecommenderEntry[]): string {
  return entries
    .map((entry) => {
      const label = recommenderLabel(entry)
      const note = entry.recommendation_note?.trim()
      return note ? `${label}: ${note}` : label
    })
    .join('\n')
}

export interface RecommenderFilterEntry {
  /** Логин рекомендовавшего (в нижнем регистре). */
  login: string
  /** Отображаемая подпись. */
  label: string
}

/**
 * Уникальные рекомендовавшие по всем строкам: Tabula и Twitch первыми,
 * затем по алфавиту. Для меню «Фильтры».
 */
export function buildRecommenderFilterEntries(
  items: WithRecommenders[],
): RecommenderFilterEntry[] {
  const byLogin = new Map<string, string>()
  for (const item of items) {
    for (const entry of item.recommenders_list) {
      const login = recLogin(entry)
      if (!login || byLogin.has(login)) continue
      byLogin.set(login, recommenderLabel(entry))
    }
  }
  const entries = [...byLogin.entries()].map(([login, label]) => ({ login, label }))
  const rank = (login: string): number =>
    login === 'tabula' ? 0 : login === 'twitch' ? 1 : 2
  return entries.sort((a, b) => {
    const diff = rank(a.login) - rank(b.login)
    if (diff !== 0) return diff
    return a.label.localeCompare(b.label, 'ru')
  })
}
