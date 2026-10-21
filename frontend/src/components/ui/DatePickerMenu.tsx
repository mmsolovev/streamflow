import { useEffect, useRef, useState } from 'react'
import { CalendarDays, X } from 'lucide-react'

import { cn } from '@/lib/cn'

/** «YYYY-MM-DD» → «ДД.ММ.ГГГГ» (дата уже локальный календарный день). */
function keyToLabel(key: string): string {
  const [year, month, day] = key.split('-')
  return `${day}.${month}.${year}`
}

/** Кнопка выбора даты с выпадающим списком реально существующих дат. */
export function DatePickerMenu({
  value,
  dates,
  onChange,
}: {
  /** Выбранная дата (ключ «YYYY-MM-DD») или '' — все даты. */
  value: string
  /** Уникальные ключи дат, по убыванию. */
  dates: string[]
  onChange: (value: string) => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handlePointer = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false)
    }
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', handlePointer)
    document.addEventListener('keydown', handleKey)
    return () => {
      document.removeEventListener('mousedown', handlePointer)
      document.removeEventListener('keydown', handleKey)
    }
  }, [open])

  if (dates.length === 0) return null

  function select(key: string) {
    onChange(key)
    setOpen(false)
  }

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
        className={cn(
          'flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm transition-colors',
          value
            ? 'border-[var(--accent)] text-[var(--accent)] [background:color-mix(in_srgb,var(--accent)_15%,transparent)]'
            : 'border-white/15 text-[var(--text)] hover:bg-white/5',
        )}
      >
        <CalendarDays className="h-4 w-4" />
        {value ? keyToLabel(value) : 'Дата'}
        {value ? (
          <span
            role="button"
            tabIndex={0}
            aria-label="Сбросить дату"
            onClick={(event) => {
              event.stopPropagation()
              select('')
            }}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.stopPropagation()
                select('')
              }
            }}
            className="-mr-1 rounded p-0.5 transition-colors hover:bg-white/10"
          >
            <X className="h-3 w-3" />
          </span>
        ) : null}
      </button>

      {open ? (
        <div className="absolute right-0 z-30 mt-2 flex max-h-96 w-44 flex-col overflow-y-auto rounded-lg border border-white/10 bg-[var(--card-bg)] p-1.5 shadow-xl shadow-black/40">
          <button
            type="button"
            onClick={() => select('')}
            className={cn(
              'flex items-center justify-between gap-2 rounded-md px-2.5 py-2 text-left text-sm transition-colors hover:bg-white/5',
              value ? 'text-[var(--text-muted)]' : 'text-[var(--accent)]',
            )}
          >
            Все даты
            {!value ? <CalendarDays className="h-3.5 w-3.5" /> : null}
          </button>
          {dates.map((key) => {
            const on = value === key
            return (
              <button
                key={key}
                type="button"
                onClick={() => select(key)}
                className={cn(
                  'flex items-center justify-between gap-2 rounded-md px-2.5 py-2 text-left text-sm transition-colors hover:bg-white/5',
                  on
                    ? 'text-[var(--accent)] [background:color-mix(in_srgb,var(--accent)_12%,transparent)]'
                    : 'text-[var(--text)]',
                )}
              >
                {keyToLabel(key)}
                {on ? <CalendarDays className="h-3.5 w-3.5" /> : null}
              </button>
            )
          })}
        </div>
      ) : null}
    </div>
  )
}
