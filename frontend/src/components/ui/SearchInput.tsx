import { Search, X } from 'lucide-react'
import { cn } from '@/lib/cn'

export function SearchInput({
  value,
  onChange,
  placeholder,
  className,
}: {
  value: string
  onChange: (value: string) => void
  placeholder?: string
  className?: string
}) {
  return (
    <div className={cn('relative', className)}>
      <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--text-muted)]" />
      <input
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="w-full rounded-md border border-white/15 bg-[var(--card-bg)] py-1.5 pl-8 pr-8 text-sm text-[var(--text)] outline-none transition-colors placeholder:text-[var(--text-muted)] focus:border-[var(--accent)]"
      />
      {value.length > 0 ? (
        <button
          type="button"
          onClick={() => onChange('')}
          onMouseDown={(event) => event.preventDefault()}
          title="Очистить"
          aria-label="Очистить"
          className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-0.5 text-[var(--text-muted)] transition-colors hover:text-[var(--text)]"
        >
          <X className="h-4 w-4" />
        </button>
      ) : null}
    </div>
  )
}
