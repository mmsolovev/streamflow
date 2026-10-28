import { ExternalLink, Plus, Trash2 } from 'lucide-react'

import type { StreamParticipant } from '@/api/types'
import { cn } from '@/lib/cn'

/** Ссылка на профиль Twitch: сохранённая в БД либо собранная из логина. */
function twitchUrl(participant: StreamParticipant): string | null {
  if (participant.twitch_url) return participant.twitch_url
  if (participant.login) return `https://www.twitch.tv/${participant.login}`
  return null
}

/**
 * Ячейка «Участники»: чипы с никнеймами и ссылками на Twitch.
 * Клик по никнейму включает фильтр по участнику. В режиме редактирования
 * рядом с чипом появляется удаление, а в конце — кнопка добавления.
 */
export function ParticipantsCell({
  participants,
  activeLogins = [],
  onLoginClick,
  canEdit,
  deletingUserId,
  onDelete,
  onAdd,
}: {
  participants: StreamParticipant[]
  /** Активные фильтры — логины в нижнем регистре. */
  activeLogins?: string[]
  onLoginClick?: (login: string) => void
  canEdit: boolean
  deletingUserId?: number | null
  onDelete?: (participant: StreamParticipant) => void
  onAdd?: () => void
}) {
  if (participants.length === 0 && !canEdit) {
    return <span className="text-[var(--text-muted)]">—</span>
  }

  return (
    <span className="flex flex-wrap items-center gap-1">
      {participants.map((participant) => {
        const label = participant.display_name || participant.login || '—'
        const login = (participant.login ?? '').toLowerCase()
        const url = twitchUrl(participant)
        const removing = deletingUserId === participant.user_id
        const active = login !== '' && activeLogins.includes(login)
        const chipClass = cn(
          'max-w-32 shrink-0 truncate rounded-full px-1.5 py-0.5 text-xs transition-colors',
          active
            ? 'bg-[var(--accent)] text-black'
            : 'bg-white/10 text-[#e5e7eb] hover:bg-white/20',
        )
        return (
          <span
            key={participant.user_id}
            className="inline-flex shrink-0 items-center gap-0.5"
          >
            {onLoginClick && login ? (
              <button
                type="button"
                onClick={() => onLoginClick(login)}
                title={`Фильтр: ${label}`}
                className={chipClass}
              >
                {label}
              </button>
            ) : (
              <span className={chipClass} title={label}>
                {label}
              </span>
            )}
            {url ? (
              <a
                href={url}
                target="_blank"
                rel="noreferrer"
                title={`Twitch: ${label}`}
                className="shrink-0 rounded-full p-0.5 text-[var(--text-muted)] transition-colors hover:text-[var(--accent)]"
              >
                <ExternalLink className="h-3 w-3" />
              </a>
            ) : null}
            {canEdit && onDelete ? (
              <button
                type="button"
                title={`Удалить участника: ${label}`}
                disabled={removing}
                onClick={() => onDelete(participant)}
                className="shrink-0 rounded-full p-0.5 text-[var(--text-muted)] transition-colors hover:text-red-400 disabled:opacity-40"
              >
                <Trash2 className="h-3 w-3" />
              </button>
            ) : null}
          </span>
        )
      })}
      {canEdit && onAdd ? (
        <button
          type="button"
          onClick={onAdd}
          title="Добавить участника"
          aria-label="Добавить участника"
          className="shrink-0 rounded-full border border-dashed border-white/25 p-0.5 text-[var(--text-muted)] transition-colors hover:border-[var(--accent)] hover:text-[var(--accent)]"
        >
          <Plus className="h-3.5 w-3.5" />
        </button>
      ) : null}
    </span>
  )
}
