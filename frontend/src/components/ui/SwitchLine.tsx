import { cn } from '@/lib/cn'

export interface SwitchItem {
  key: string
  label: string
}

/**
 * Длинная линия с переключателями (подразделы раздела).
 *
 * Активный переключатель подсвечен акцентом и подчёркнут; сама линия тянется
 * на всю ширину блока.
 */
export function SwitchLine({
  items,
  activeKey,
  onSelect,
}: {
  items: SwitchItem[]
  activeKey: string
  onSelect: (key: string) => void
}) {
  return (
    <div className="flex items-stretch border-b border-white/10">
      {items.map((item) => {
        const active = item.key === activeKey
        return (
          <button
            type="button"
            key={item.key}
            onClick={() => onSelect(item.key)}
            aria-pressed={active}
            className={cn(
              '-mb-px border-b-2 px-4 py-2.5 text-sm uppercase tracking-wider transition-colors',
              active
                ? 'border-[var(--accent)] text-[var(--accent)]'
                : 'border-transparent text-[var(--text-muted)] hover:text-[var(--text)]',
            )}
          >
            {item.label}
          </button>
        )
      })}
    </div>
  )
}
