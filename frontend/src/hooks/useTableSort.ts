import { useCallback, useMemo, useState } from 'react'

import type { EntityColumn, SortDir } from '@/components/entity/types'

export interface SortState {
  key: string
  dir: SortDir
}

/**
 * Сортировка строк таблицы по колонкам.
 * Клик по новой колонке — её `defaultDir` (обычно убывание); повторный клик
 * по той же — переключение направления.
 */
export function useTableSort<T>(
  rows: T[],
  columns: EntityColumn<T>[],
  initial: SortState,
) {
  const [state, setState] = useState<SortState>(initial)

  const sorted = useMemo(() => {
    const column = columns.find((item) => item.key === state.key)
    if (!column?.sortValue) return rows
    const { sortValue, tieBreaks } = column
    const factor = state.dir === 'asc' ? 1 : -1
    return [...rows].sort((a, b) => {
      const left = sortValue(a)
      const right = sortValue(b)
      const primary =
        typeof left === 'number' && typeof right === 'number'
          ? left - right
          : String(left).localeCompare(String(right), 'ru')
      if (primary !== 0) return primary * factor
      for (const tieBreak of tieBreaks ?? []) {
        const result = tieBreak(a, b)
        if (result !== 0) return result
      }
      return 0
    })
  }, [rows, columns, state])

  const onSort = useCallback(
    (key: string) => {
      const column = columns.find((item) => item.key === key)
      if (!column?.sortValue) return
      setState((prev) =>
        prev.key === key
          ? { key, dir: prev.dir === 'asc' ? 'desc' : 'asc' }
          : { key, dir: column.defaultDir ?? 'desc' },
      )
    },
    [columns],
  )

  return { rows: sorted, sortKey: state.key, sortDir: state.dir, onSort }
}
