import type { CSSProperties } from 'react'

import { cn } from '@/lib/cn'

/** Заглушка-плейсхолдер на время загрузки. */
export function Skeleton({
  className,
  style,
}: {
  className?: string
  style?: CSSProperties
}) {
  return (
    <div
      aria-hidden
      className={cn('animate-pulse rounded-md bg-white/[0.06]', className)}
      style={style}
    />
  )
}

/**
 * Скелетон таблицы: повторяет сетку колонок и строк, чтобы страница
 * не «мигала» пустотой при загрузке.
 */
export function TableSkeleton({
  columns = 6,
  rows = 6,
}: {
  /** Сколько колонок нарисовать в шапке. */
  columns?: number
  /** Сколько строк-островков показать. */
  rows?: number
}) {
  return (
    <div className="space-y-3 p-6">
      <div className="flex gap-3">
        {Array.from({ length: columns }).map((_, index) => (
          <Skeleton
            key={index}
            className="h-3 flex-1"
            // Разная ширина колонок — таблица выглядит живее.
            style={{ flexGrow: index === 1 ? 3 : 1 }}
          />
        ))}
      </div>
      {Array.from({ length: rows }).map((_, rowIndex) => (
        <div key={rowIndex} className="flex items-center gap-3">
          {Array.from({ length: columns }).map((__, colIndex) => (
            <Skeleton
              key={colIndex}
              className="h-4 flex-1"
              style={{ flexGrow: colIndex === 1 ? 3 : 1 }}
            />
          ))}
        </div>
      ))}
    </div>
  )
}
