import { EntityTable } from '@/components/entity/EntityTable'
import type { EntityColumn, SortDir } from '@/components/entity/types'

/**
 * Список сущностей: на широких экранах — таблица-«островки», на узких —
 * карточки (таблица с горизонтальной прокруткой неудобна на телефоне).
 */
export function EntityList<T>({
  columns,
  rows,
  rowKey,
  sortKey,
  sortDir,
  onSort,
  gridTemplate,
  activeFilters = [],
  onFilterToggle,
  highlightedRowKey,
  rowClassName,
  minWidth = '1120px',
}: {
  columns: EntityColumn<T>[]
  rows: T[]
  rowKey: (row: T) => string | number
  sortKey: string
  sortDir: SortDir
  onSort: (key: string) => void
  gridTemplate: string
  activeFilters?: string[]
  onFilterToggle?: (key: string) => void
  highlightedRowKey?: string | number | null
  rowClassName?: string
  /** Минимальная ширина таблицы (горизонтальная прокрутка на узких экранах). */
  minWidth?: string
}) {
  return (
    <>
      {/* Широкие экраны — привычная таблица. */}
      <div className="hidden overflow-x-auto lg:block">
        <div style={{ minWidth }}>
          <EntityTable
            columns={columns}
            rows={rows}
            rowKey={rowKey}
            sortKey={sortKey}
            sortDir={sortDir}
            onSort={onSort}
            activeFilters={activeFilters}
            onFilterToggle={onFilterToggle}
            gridTemplate={gridTemplate}
            highlightedRowKey={highlightedRowKey}
            rowClassName={rowClassName}
          />
        </div>
      </div>

      {/* Узкие экраны — карточки: первая колонка заголовком, остальные — строки. */}
      <ul className="flex flex-col gap-3 lg:hidden">
        {rows.map((row) => {
          const [titleColumn, ...restColumns] = columns
          return (
            <li
              key={rowKey(row)}
              data-row-key={String(rowKey(row))}
              className="rounded-xl border border-[var(--accent)] bg-[var(--card-bg)] px-3 py-3"
            >
              <div className="mb-2 text-base font-medium text-[var(--text)]">
                {titleColumn.render(row)}
              </div>
              <dl className="flex flex-col">
                {restColumns.map((column) => (
                  <div
                    key={column.key}
                    className="flex items-baseline justify-between gap-3 border-b border-white/5 py-1.5 last:border-b-0"
                  >
                    <dt className="shrink-0 text-xs uppercase tracking-wide text-[var(--text-muted)]">
                      {column.label}
                    </dt>
                    <dd className="min-w-0 text-right text-sm text-[var(--text)]">
                      {column.render(row)}
                    </dd>
                  </div>
                ))}
              </dl>
            </li>
          )
        })}
      </ul>
    </>
  )
}
