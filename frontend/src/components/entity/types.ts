import type { ReactNode } from 'react'

export type SortDir = 'asc' | 'desc'

/** Ширина колонки «Теги» — зафиксирована, чтобы она совпадала во всех таблицах. */
export const TAGS_COLUMN_WIDTH = '200px'

/** Описание колонки таблицы-«островка». */
export interface EntityColumn<T> {
  key: string
  label: string
  /** Значение для сортировки. Нет — колонка не сортируется. */
  sortValue?: (row: T) => string | number
  /**
   * Предикат «ячейка заполнена». Нет — заголовок не кликабелен. Есть — клик по
   * заголовку включает фильтр, оставляющий строки, где предикат истинен.
   */
  filterValue?: (row: T) => boolean
  /** Направление при первом клике (по умолчанию — убывание). */
  defaultDir?: SortDir
  /** Дополнительные компараторы при равенстве основного ключа (всегда по возрастанию). */
  tieBreaks?: ((a: T, b: T) => number)[]
  /** Не переводить заголовок в верхний регистр (напр. аббревиатуры/бренды). */
  noUppercase?: boolean
  align?: 'left' | 'right' | 'center'
  /** Доп. классы для ячейки (напр. ширины уже задаются grid-шаблоном). */
  className?: string
  render: (row: T) => ReactNode
}
