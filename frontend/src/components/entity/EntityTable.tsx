import { ArrowDown, ArrowUp } from 'lucide-react'

import type { EntityColumn, SortDir } from '@/components/entity/types'
import { cn } from '@/lib/cn'

function cellAlign(align?: 'left' | 'right' | 'center') {
  if (align === 'right') return 'justify-end text-right'
  if (align === 'center') return 'justify-center text-center'
  return ''
}

/** Тонкий вертикальный разделитель между колонками (цветом акцента). */
const DIVIDER = 'border-l [border-color:color-mix(in_srgb,var(--accent)_35%,transparent)]'

/**
 * Таблица-«островник»: общая шапка с колонками (клик — сортировка) и строки
 * во всю ширину, идущие одна под другой.
 */
export function EntityTable<T>({
  columns,
  rows,
  rowKey,
  sortKey,
  sortDir,
  onSort,
  gridTemplate,
  activeFilters = [],
  onFilterToggle,
  rowClassName,
  highlightedRowKey,
}: {
  columns: EntityColumn<T>[]
  rows: T[]
  rowKey: (row: T) => string | number
  sortKey: string
  sortDir: SortDir
  onSort: (key: string) => void
  gridTemplate: string
  /** Ключи колонок с активным фильтром «ячейка заполнена». */
  activeFilters?: string[]
  /** Переключатель фильтра колонки (клик по её заголовку). */
  onFilterToggle?: (key: string) => void
  /** Доп. классы строки (напр. иная минимальная высота «островка»). */
  rowClassName?: string
  /** Ключ строки, которую нужно подсветить (например, только что добавленная игра). */
  highlightedRowKey?: string | number | null
}) {
  return (
    <div className="flex flex-col">
      <div
        className="grid gap-x-3 rounded-lg border-[0.5px] border-white/10 bg-black/20 px-4 py-2.5 text-xs tracking-wide text-[#f3f4f6]"
        style={{ gridTemplateColumns: gridTemplate }}
      >
        {columns.map((column, index) => {
          const active = sortKey === column.key
          const sortable = Boolean(column.sortValue)
          const filterable = Boolean(column.filterValue) && Boolean(onFilterToggle)
          const filterActive = activeFilters.includes(column.key)
          const caseClass = column.noUppercase ? 'normal-case' : 'uppercase'
          return (
            <div
              key={column.key}
              className={cn(
                'flex min-w-0 items-center justify-center gap-1 text-center',
                index > 0 && `pl-3 ${DIVIDER}`,
              )}
            >
              {sortable ? (
                <button
                  type="button"
                  onClick={() => onSort(column.key)}
                  className={cn(
                    'inline-flex items-center gap-1 transition-colors hover:text-[var(--accent)]',
                    active && 'text-[var(--accent)]',
                  )}
                >
                  <span className={cn('truncate', caseClass)}>{column.label}</span>
                  {active ? (
                    sortDir === 'asc' ? (
                      <ArrowUp className="h-3 w-3 shrink-0" />
                    ) : (
                      <ArrowDown className="h-3 w-3 shrink-0" />
                    )
                  ) : null}
                </button>
              ) : filterable ? (
                <button
                  type="button"
                  onClick={() => onFilterToggle?.(column.key)}
                  title="Показать только заполненные"
                  className={cn(
                    'inline-flex min-w-0 items-center transition-colors hover:text-[var(--accent)]',
                    filterActive && 'text-[var(--accent)]',
                  )}
                >
                  <span className={cn('truncate', caseClass)}>{column.label}</span>
                </button>
              ) : (
                <span className={cn('truncate', caseClass)}>{column.label}</span>
              )}
            </div>
          )
        })}
      </div>

      <div className="mt-2 flex flex-col gap-2">
        {rows.map((row) => {
          const key = rowKey(row)
          const highlighted =
            highlightedRowKey !== null &&
            highlightedRowKey !== undefined &&
            String(key) === String(highlightedRowKey)
          return (
            <div
              key={key}
              data-row-key={String(key)}
              className={cn(
                'grid min-h-[3.75rem] items-stretch gap-x-3 rounded-xl border-[0.5px] border-[var(--accent)] bg-[var(--card-bg)] px-4 py-3 transition-colors hover:[background:color-mix(in_srgb,var(--card-bg)_88%,var(--accent))]',
                rowClassName,
                highlighted &&
                  'ring-2 ring-[var(--accent)] [background:color-mix(in_srgb,var(--card-bg)_85%,var(--accent))]',
              )}
              style={{ gridTemplateColumns: gridTemplate }}
            >
              {columns.map((column, index) => (
                <div
                  key={column.key}
                  className={cn(
                    'flex min-w-0 items-center gap-2 text-base text-[#e5e7eb]',
                    index > 0 && `pl-3 ${DIVIDER}`,
                    cellAlign(column.align),
                    column.className,
                  )}
                >
                  {column.render(row)}
                </div>
              ))}
            </div>
          )
        })}
      </div>
    </div>
  )
}
