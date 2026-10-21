import { cn } from '@/lib/cn'

/**
 * Теги «таблетками» с разделителем `|` между группами (платформы | жанры).
 * Каждый тег кликабелен — вызывает фильтр по нему.
 */
export function TagsCell({
  groups,
  activeTags,
  onTagClick,
}: {
  groups: string[][]
  activeTags: string[]
  onTagClick: (value: string) => void
}) {
  const nonEmpty = groups.filter((group) => group.length > 0)
  if (nonEmpty.length === 0) {
    return <span className="text-[var(--text-muted)]">—</span>
  }
  return (
    <span className="flex flex-wrap items-center gap-1">
      {nonEmpty.map((group, groupIndex) => (
        <span
          key={`${groupIndex}-${group.join(',')}`}
          className="inline-flex flex-wrap items-center gap-1"
        >
          {group.map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => onTagClick(value)}
              title={`Фильтр по тегу: ${value}`}
              className={cn(
                'rounded-full px-1.5 py-0.5 text-xs transition-colors',
                activeTags.includes(value)
                  ? 'bg-[var(--accent)] text-black'
                  : 'bg-white/10 text-[var(--text-muted)] hover:text-[var(--text)]',
              )}
            >
              {value}
            </button>
          ))}
          {/* Разделитель — в конце группы, чтобы при переносе оставался сверху. */}
          {groupIndex < nonEmpty.length - 1 ? (
            <span className="text-[var(--text-muted)]">|</span>
          ) : null}
        </span>
      ))}
    </span>
  )
}
