import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Search, X } from 'lucide-react'

import type { GameCandidate } from '@/api/types'
import { useSearchRecommendationCandidates } from '@/features/recommendations/useRecommendations'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { cn } from '@/lib/cn'

export interface IGDBRefreshSource {
  igdbId?: string
  igdbUrl?: string
}

export function GameIGDBRefreshModal({
  gameName,
  onClose,
  onSubmit,
}: {
  gameName: string
  onClose: () => void
  onSubmit: (source: IGDBRefreshSource) => Promise<void>
}) {
  const [search, setSearch] = useState(gameName)
  const [selected, setSelected] = useState<GameCandidate | null>(null)
  const [igdbUrl, setIgdbUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const debouncedSearch = useDebouncedValue(search.trim())
  const candidatesQuery = useSearchRecommendationCandidates(debouncedSearch)
  const candidates = candidatesQuery.data?.candidates ?? []

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busy) onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [busy, onClose])

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const url = igdbUrl.trim()
    const igdbId = selected?.igdb_id
    if ((!url && !igdbId) || busy) return

    setBusy(true)
    try {
      await onSubmit(url ? { igdbUrl: url } : { igdbId })
      onClose()
    } catch {
      // Ошибку показывает React Query mutation.
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={() => {
        if (!busy) onClose()
      }}
    >
      <div
        onClick={(event) => event.stopPropagation()}
        className="flex max-h-[calc(100dvh-3rem)] w-full max-w-lg flex-col overflow-hidden rounded-lg border border-white/10 bg-[var(--card-bg)] shadow-xl shadow-black/40"
      >
        <div className="flex shrink-0 items-center justify-between border-b border-white/10 px-5 py-3">
          <h2 className="font-social text-sm uppercase tracking-wide text-[var(--text)]">
            Обновить данные IGDB
          </h2>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded-md p-1.5 text-[var(--text-muted)] transition-colors hover:text-[var(--text)] disabled:opacity-40"
            aria-label="Закрыть"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <form onSubmit={submit} className="flex min-h-0 flex-1 flex-col">
          <div className="space-y-3 px-5 py-4">
            <div className="space-y-1">
              <label
                htmlFor="igdb-game-search"
                className="block text-xs uppercase tracking-wide text-[var(--text-muted)]"
              >
                Найти игру в IGDB
              </label>
              <div className="relative">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--text-muted)]" />
                <input
                  id="igdb-game-search"
                  autoFocus
                  value={search}
                  onChange={(event) => {
                    setSearch(event.target.value)
                    setSelected(null)
                  }}
                  placeholder="Название игры"
                  className="w-full rounded-md border border-white/15 bg-[var(--section-bg)] py-1.5 pl-9 pr-3 text-sm text-[var(--text)] outline-none transition-colors placeholder:text-[var(--text-muted)] focus:border-[var(--accent)]"
                />
              </div>
            </div>

            <div className="space-y-1">
              <label
                htmlFor="igdb-game-url"
                className="block text-xs uppercase tracking-wide text-[var(--text-muted)]"
              >
                Или вставить ссылку на IGDB
              </label>
              <input
                id="igdb-game-url"
                type="url"
                value={igdbUrl}
                onChange={(event) => {
                  setIgdbUrl(event.target.value)
                  if (event.target.value) setSelected(null)
                }}
                placeholder="https://www.igdb.com/games/..."
                className="w-full rounded-md border border-white/15 bg-[var(--section-bg)] px-3 py-1.5 text-sm text-[var(--text)] outline-none transition-colors placeholder:text-[var(--text-muted)] focus:border-[var(--accent)]"
              />
            </div>
            {selected && !igdbUrl.trim() ? (
              <p className="text-xs text-[var(--text-muted)]">
                Выбрано: {selected.title} (IGDB ID {selected.igdb_id})
              </p>
            ) : null}
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto border-t border-white/10 px-5 py-2">
            {igdbUrl.trim() ? (
              <p className="py-2 text-xs text-[var(--text-muted)]">
                ID будет извлечён из ссылки IGDB.
              </p>
            ) : debouncedSearch.length < 2 ? (
              <p className="py-2 text-xs text-[var(--text-muted)]">
                Введите минимум 2 символа, чтобы увидеть варианты.
              </p>
            ) : candidatesQuery.isLoading ? (
              <p className="py-2 text-xs text-[var(--text-muted)]">Поиск вариантов…</p>
            ) : candidates.length === 0 ? (
              <p className="py-2 text-xs text-[var(--text-muted)]">Ничего не найдено.</p>
            ) : (
              <div className="space-y-1.5 py-1">
                {candidates.map((candidate) => {
                  const isSelected = selected?.igdb_id === candidate.igdb_id
                  return (
                    <button
                      type="button"
                      key={candidate.igdb_id}
                      onClick={() => {
                        setSelected(isSelected ? null : candidate)
                        setIgdbUrl('')
                      }}
                      className={cn(
                        'w-full rounded-md border px-3 py-2 text-left transition-colors',
                        isSelected
                          ? 'border-[var(--accent)] bg-[color-mix(in_srgb,var(--accent)_15%,transparent)]'
                          : 'border-white/10 hover:bg-white/5',
                      )}
                    >
                      <span className="flex items-baseline justify-between gap-2">
                        <span className="min-w-0 text-sm font-medium text-[var(--text)]">
                          {candidate.title}
                        </span>
                        {candidate.release_year ? (
                          <span className="shrink-0 text-xs text-[var(--text-muted)]">
                            {candidate.release_year}
                          </span>
                        ) : null}
                      </span>
                      {candidate.platforms || candidate.genres ? (
                        <span className="mt-1 block truncate text-xs text-[var(--text-muted)]">
                          {[candidate.platforms, candidate.genres]
                            .filter(Boolean)
                            .join(' • ')}
                        </span>
                      ) : null}
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
              disabled={busy}
              className="rounded-md border border-white/15 px-3 py-1.5 text-sm text-[var(--text)] transition-colors hover:bg-white/5 disabled:opacity-40"
            >
              Отмена
            </button>
            <button
              type="submit"
              disabled={busy || (!igdbUrl.trim() && !selected)}
              className="rounded-md bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-black transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {busy ? 'Обновление…' : 'Обновить'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
