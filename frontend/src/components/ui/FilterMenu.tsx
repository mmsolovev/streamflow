import { useEffect, useMemo, useRef, useState } from 'react'
import { Check, Search, SlidersHorizontal } from 'lucide-react'

import { cn } from '@/lib/cn'

export interface FilterOption {
  key: string
  label: string
}

/** С этого числа фильтров в меню появляется строка поиска. */
const SEARCH_THRESHOLD = 8

/** Кнопка «Фильтры» с выпадающим списком — несколько фильтров одновременно. */
export function FilterMenu({
  options,
  active,
  onToggle,
  onClear,
}: {
  options: FilterOption[]
  active: string[]
  onToggle: (key: string) => void
  onClear: () => void
}) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const ref = useRef<HTMLDivElement>(null)

  const close = () => {
    setOpen(false)
    setSearch('')
  }

  useEffect(() => {
    if (!open) return
    const handlePointer = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) close()
    }
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') close()
    }
    document.addEventListener('mousedown', handlePointer)
    document.addEventListener('keydown', handleKey)
    return () => {
      document.removeEventListener('mousedown', handlePointer)
      document.removeEventListener('keydown', handleKey)
    }
  }, [open])

  const visibleOptions = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return options
    return options.filter((option) => option.label.toLowerCase().includes(q))
  }, [options, search])

  if (options.length === 0) return null
  const showSearch = options.length > SEARCH_THRESHOLD

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => (open ? close() : setOpen(true))}
        aria-expanded={open}
        className={cn(
          'flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm transition-colors',
          active.length > 0
            ? 'border-[var(--accent)] text-[var(--accent)] [background:color-mix(in_srgb,var(--accent)_15%,transparent)]'
            : 'border-white/15 text-[var(--text)] hover:bg-white/5',
        )}
      >
        <SlidersHorizontal className="h-4 w-4" />
        Фильтры
        {active.length > 0 ? (
          <span className="rounded-full bg-[var(--accent)] px-1.5 text-xs text-black">
            {active.length}
          </span>
        ) : null}
      </button>

      {open ? (
        <div className="absolute right-0 z-30 mt-2 flex max-h-96 w-64 max-w-[calc(100vw-2rem)] flex-col overflow-hidden rounded-lg border border-white/10 bg-[var(--card-bg)] p-1.5 shadow-xl shadow-black/40">
          {showSearch ? (
            <div className="relative mb-1 border-b border-white/10 pb-1.5">
              <Search className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--text-muted)]" />
              <input
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Поиск фильтра…"
                className="w-full rounded-md bg-transparent py-1.5 pl-8 pr-2 text-sm text-[var(--text)] outline-none placeholder:text-[var(--text-muted)]"
              />
            </div>
          ) : null}
          <div className="flex flex-col overflow-y-auto">
            {visibleOptions.map((option) => {
              const on = active.includes(option.key)
              return (
                <button
                  key={option.key}
                  type="button"
                  onClick={() => onToggle(option.key)}
                  className="flex items-center gap-2 rounded-md px-2.5 py-2 text-left text-sm text-[var(--text)] transition-colors hover:bg-white/5"
                >
                  <span
                    className={cn(
                      'flex h-4 w-4 shrink-0 items-center justify-center rounded border transition-colors',
                      on
                        ? 'border-[var(--accent)] bg-[var(--accent)] text-black'
                        : 'border-white/25',
                    )}
                  >
                    {on ? <Check className="h-3 w-3" /> : null}
                  </span>
                  <span className="truncate">{option.label}</span>
                </button>
              )
            })}
            {visibleOptions.length === 0 ? (
              <p className="px-2.5 py-2 text-sm text-[var(--text-muted)]">
                Ничего не найдено
              </p>
            ) : null}
          </div>
          {active.length > 0 ? (
            <button
              type="button"
              onClick={onClear}
              className="mt-1 rounded-md px-2.5 py-1.5 text-left text-xs text-[var(--text-muted)] transition-colors hover:text-[var(--text)]"
            >
              Сбросить фильтры
            </button>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
