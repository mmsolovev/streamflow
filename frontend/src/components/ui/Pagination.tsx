import { ChevronLeft, ChevronRight } from 'lucide-react'

import { cn } from '@/lib/cn'

export function Pagination({
  total,
  limit,
  offset,
  onChange,
}: {
  total: number
  limit: number
  offset: number
  onChange: (offset: number) => void
}) {
  if (total <= limit) return null

  const pageCount = Math.max(1, Math.ceil(total / limit))
  const page = Math.floor(offset / limit) + 1

  const go = (next: number) => {
    const clamped = Math.min(Math.max(1, next), pageCount)
    onChange((clamped - 1) * limit)
  }

  const buttonClass =
    'flex items-center gap-1 rounded-md border border-white/15 px-3 py-1.5 text-sm text-[var(--text)] transition-colors hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-40'

  const pageBtn =
    'flex h-8 min-w-8 items-center justify-center rounded-md border border-white/10 px-2 text-sm transition-colors hover:bg-white/5'

  const pages: (number | '...')[] = []
  const maxShown = 5
  if (pageCount <= maxShown + 2) {
    for (let i = 1; i <= pageCount; i++) pages.push(i)
  } else {
    pages.push(1)
    if (page > 3) pages.push('...')
    const start = Math.max(2, page - 1)
    const end = Math.min(pageCount - 1, page + 1)
    for (let i = start; i <= end; i++) pages.push(i)
    if (page < pageCount - 2) pages.push('...')
    pages.push(pageCount)
  }

  return (
    <div className="flex flex-wrap items-center justify-center gap-2 py-2 text-sm">
      <button
        type="button"
        className={cn(buttonClass)}
        disabled={page <= 1}
        onClick={() => go(page - 1)}
      >
        <ChevronLeft className="h-4 w-4" />
        Назад
      </button>
      {pages.map((p, idx) =>
        p === '...' ? (
          <span key={`dots-${idx}`} className="px-2 text-[var(--text-muted)]">
            ...
          </span>
        ) : (
          <button
            key={p}
            type="button"
            onClick={() => go(p)}
            className={cn(
              pageBtn,
              page === p ? 'bg-[var(--accent)] text-black' : 'text-[var(--text)]',
            )}
          >
            {p}
          </button>
        ),
      )}
      <button
        type="button"
        className={cn(buttonClass)}
        disabled={page >= pageCount}
        onClick={() => go(page + 1)}
      >
        Вперёд
        <ChevronRight className="h-4 w-4" />
      </button>
    </div>
  )
}
