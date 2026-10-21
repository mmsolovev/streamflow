import { Link } from 'react-router-dom'
import { Trash2 } from 'lucide-react'

import {
  recLogin,
  recommendersTooltip,
  recommenderLabel,
  sortRecommenderEntries,
  type RecommenderEntry,
} from '@/lib/recommenders'
import { cn } from '@/lib/cn'

/**
 * Сколько рекомендовавших показывать, пока ячейка не «переполнится».
 * Ячейка одной строки (без расширения): при большом числе рекомендующих
 * в конце появляется кнопка «ещё».
 */
const MAX_VISIBLE = 2

/**
 * Ячейка «Рекомендуют»: количество (ссылка на игру) + чипы рекомендовавших.
 * Чип кликабелен — включает фильтр по рекомендовавшему; при наведении
 * всплывает его `recommendation_note`. Для тех, кому разрешено удаление,
 * рядом с чипом появляется кнопка удаления его рекомендации.
 */
export function RecommendersCell({
  gameId,
  entries,
  activeLogins,
  onLoginClick,
  count,
  canDelete,
  onDelete,
  deletingLogin,
}: {
  gameId: number
  entries: RecommenderEntry[]
  /** Активные фильтры — логины в нижнем регистре. */
  activeLogins: string[]
  onLoginClick: (login: string) => void
  /** Число рекомендовавших (по умолчанию — длина списка). */
  count?: number
  /** Можно ли удалить рекомендацию от данного логина (свою или как админ). */
  canDelete?: (login: string) => boolean
  /** Удалить рекомендацию от данного логина. */
  onDelete?: (login: string) => void
  /** Логин, чью рекомендацию сейчас удаляют (для disabled). */
  deletingLogin?: string | null
}) {
  if (entries.length === 0) {
    return <span className="text-[var(--text-muted)]">—</span>
  }
  const sorted = sortRecommenderEntries(entries)
  const visible = sorted.slice(0, MAX_VISIBLE)
  const hidden = sorted.slice(MAX_VISIBLE)
  const total = count ?? sorted.length
  const gameLink = `/games/${gameId}`

  return (
    <span className="flex min-w-0 items-center gap-1 text-sm">
      <Link
        to={gameLink}
        title="Открыть игру"
        className="shrink-0 font-medium text-[var(--accent)] transition-opacity hover:opacity-80"
      >
        {total}
      </Link>
      {visible.map((entry) => {
        const login = recLogin(entry)
        const label = recommenderLabel(entry)
        const note = entry.recommendation_note?.trim()
        const removable = canDelete?.(login) ?? false
        return (
          <span key={login} className="inline-flex shrink-0 items-center gap-0.5">
            <button
              type="button"
              onClick={() => onLoginClick(login)}
              title={note || `Фильтр: ${label}`}
              className={cn(
                'shrink-0 rounded-full px-1.5 py-0.5 text-xs transition-colors',
                activeLogins.includes(login)
                  ? 'bg-[var(--accent)] text-black'
                  : 'bg-white/10 text-[#e5e7eb] hover:bg-white/20',
              )}
            >
              {label}
            </button>
            {removable && onDelete ? (
              <button
                type="button"
                title={`Удалить рекомендацию: ${label}`}
                disabled={deletingLogin === login}
                onClick={() => onDelete(login)}
                className="shrink-0 rounded-full p-0.5 text-[var(--text-muted)] transition-colors hover:text-red-400 disabled:opacity-40"
              >
                <Trash2 className="h-3 w-3" />
              </button>
            ) : null}
          </span>
        )
      })}
      {hidden.length > 0 ? (
        <Link
          to={gameLink}
          title={recommendersTooltip(hidden)}
          className="shrink-0 rounded-full px-1.5 py-0.5 text-xs text-[#e5e7eb] transition-colors hover:bg-white/10"
        >
          ещё
        </Link>
      ) : null}
    </span>
  )
}
