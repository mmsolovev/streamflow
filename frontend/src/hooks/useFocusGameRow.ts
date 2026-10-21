import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

interface FocusGameRowOptions {
  /** Отсортированный и отфильтрованный список игр текущего раздела. */
  rows: Array<{ id: number }>
  /** Полный список раздела без учёта поиска/фильтров. */
  allRows?: Array<{ id: number }>
  /** Сброс поискового запроса, если игра скрыта фильтром. */
  clearFilters?: () => void
  /** Размер страницы списка. */
  pageSize: number
  /** Текущее смещение списка. */
  offset: number
  /** Установщик смещения списка. */
  setOffset: (next: number) => void
}

/**
 * Переводит список к строке с только что добавленной игрой.
 *
 * Идентификатор игры передаётся в query-параметре `focus` (например,
 * `/recommendations?focus=42`). Хук пролистывает список до нужной страницы,
 * подсвечивает строку и прокручивает к ней.
 */
export function useFocusGameRow({
  rows,
  allRows,
  clearFilters,
  pageSize,
  offset,
  setOffset,
}: FocusGameRowOptions) {
  const [params] = useSearchParams()
  const raw = params.get('focus')
  const focusId = raw && /^\d+$/.test(raw) ? Number(raw) : null
  const [highlightId, setHighlightId] = useState<number | null>(null)

  // `setOffset` нестабилен (react-router пересоздаёт его при смене query),
  // поэтому держим его в ref, чтобы не перезапускать эффект лишний раз.
  const setOffsetRef = useRef(setOffset)
  useEffect(() => {
    setOffsetRef.current = setOffset
  }, [setOffset])

  useEffect(() => {
    if (focusId === null) return
    const index = rows.findIndex((item) => item.id === focusId)
    if (index < 0) {
      // Игра есть в разделе, но скрыта поиском/фильтрами — сбрасываем их.
      if (allRows && clearFilters && allRows.some((item) => item.id === focusId)) {
        clearFilters()
      }
      return
    }
    const targetOffset = Math.floor(index / pageSize) * pageSize
    if (offset !== targetOffset) {
      setOffsetRef.current(targetOffset)
      return
    }
    // Ждём кадра, чтобы строка успела отрисоваться, и только затем скроллим.
    const frame = window.requestAnimationFrame(() => {
      setHighlightId(focusId)
      const node = document.querySelector(`[data-row-key="${focusId}"]`)
      node?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    })
    return () => window.cancelAnimationFrame(frame)
  }, [focusId, rows, allRows, clearFilters, offset, pageSize])

  // Подсветка гаснет через несколько секунд.
  useEffect(() => {
    if (highlightId === null) return
    const timer = window.setTimeout(() => setHighlightId(null), 4000)
    return () => window.clearTimeout(timer)
  }, [highlightId])

  return { focusId, highlightId }
}
