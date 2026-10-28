import { useEffect, useMemo, useState } from 'react'
import { Search, User, X } from 'lucide-react'
import { toast } from 'sonner'
import { useQuery } from '@tanstack/react-query'

import type { UserSuggestion, UsersPage } from '@/api/types'
import { api } from '@/api/client'
import { useAddStreamParticipant } from '@/features/streams/useStreams'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { cn } from '@/lib/cn'

async function searchUsers(query: string): Promise<UserSuggestion[]> {
  if (query.trim().length < 2) return []
  const { data } = await api.get<UsersPage>('/users/search', {
    params: { q: query.trim(), limit: 20 },
  })
  return data.items ?? []
}

/** Модальное окно добавления участника на стрим. */
export function AddParticipantModal({
  streamId,
  streamLabel,
  existingLogins,
  onClose,
}: {
  streamId: number
  streamLabel: string
  existingLogins: string[]
  onClose: () => void
}) {
  const [search, setSearch] = useState('')
  const debounced = useDebouncedValue(search)
  const [selected, setSelected] = useState<UserSuggestion | null>(null)
  const mutation = useAddStreamParticipant()

  const existing = useMemo(
    () => new Set(existingLogins.map((login) => login.toLowerCase())),
    [existingLogins],
  )

  const { data: candidates = [], isLoading } = useQuery({
    queryKey: ['users', 'search', debounced.trim()],
    queryFn: () => searchUsers(debounced),
    enabled: debounced.trim().length >= 2,
    staleTime: 30_000,
  })

  const available = candidates.filter(
    (candidate) => !existing.has((candidate.login ?? '').toLowerCase()),
  )

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const submit = () => {
    const login = selected?.login
    if (!login || mutation.isPending) return
    mutation.mutate(
      { streamId, login },
      {
        onSuccess: (result) => {
          toast.success(result.message || 'Участник добавлен.')
          onClose()
        },
        onError: (error) => toast.error(error.message),
      },
    )
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="flex max-h-[calc(100dvh-3rem)] w-full max-w-lg flex-col overflow-hidden rounded-lg border border-white/10 bg-[var(--card-bg)] shadow-xl shadow-black/40">
        <div className="flex shrink-0 items-center justify-between border-b border-white/10 px-5 py-3">
          <h2 className="font-social text-sm uppercase tracking-wide text-[var(--text)]">
            Добавить участника
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1.5 text-[var(--text-muted)] transition-colors hover:text-[var(--text)]"
            aria-label="Закрыть"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-3 px-5 py-4">
          <p className="text-xs text-[var(--text-muted)]">{streamLabel}</p>
          <div className="relative">
            <User className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--text-muted)]" />
            <input
              value={selected ? selected.display_name || selected.login || '' : search}
              onChange={(event) => {
                setSelected(null)
                setSearch(event.target.value)
              }}
              placeholder="Никнейм пользователя"
              autoFocus
              className="w-full rounded-md border border-white/15 bg-[var(--card-bg)] py-1.5 pl-9 pr-3 text-sm text-[var(--text)] outline-none transition-colors placeholder:text-[var(--text-muted)] focus:border-[var(--accent)]"
            />
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto border-t border-white/10 px-5 py-2">
          {debounced.trim().length < 2 ? (
            <p className="py-2 text-xs text-[var(--text-muted)]">
              Введите минимум 2 символа, чтобы найти никнейм.
            </p>
          ) : isLoading ? (
            <p className="py-2 text-xs text-[var(--text-muted)]">Поиск никнеймов…</p>
          ) : available.length === 0 ? (
            <p className="py-2 text-xs text-[var(--text-muted)]">Никнеймы не найдены.</p>
          ) : (
            <div className="space-y-1 py-1">
              {available.map((candidate) => {
                const isSelected = selected?.login === candidate.login
                return (
                  <button
                    type="button"
                    key={candidate.login}
                    onClick={() => setSelected(candidate)}
                    className={cn(
                      'flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm font-medium transition-colors',
                      isSelected
                        ? 'bg-[color-mix(in_srgb,var(--accent)_20%,transparent)] text-[var(--accent)]'
                        : 'text-[var(--text)] hover:bg-white/5',
                    )}
                  >
                    <Search className="h-3.5 w-3.5 shrink-0 text-[var(--text-muted)]" />
                    <span className="min-w-0 truncate">
                      {candidate.display_name || candidate.login}
                    </span>
                  </button>
                )
              })}
            </div>
          )}
        </div>

        <div className="flex shrink-0 items-center justify-end gap-2 border-t border-white/10 px-5 py-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-white/15 px-3 py-1.5 text-sm text-[var(--text)] transition-colors hover:bg-white/5"
          >
            Отмена
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={!selected || mutation.isPending}
            className="rounded-md bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-black transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {mutation.isPending ? 'Добавление…' : 'Добавить'}
          </button>
        </div>
      </div>
    </div>
  )
}
