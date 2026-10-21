import { useCallback, useEffect, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'

/**
 * Сбрасывает offset в 0 при смене зависимостей (поиск, фильтры, сортировка).
 *
 * Сам setter намеренно не входит в deps: в react-router v7 `setSearchParams`
 * пересоздаётся при каждом изменении query-строки, поэтому запись `?offset=24`
 * иначе перезапускала бы эффект и возвращала бы первую страницу.
 */
export function useResetOffsetOn(setOffset: (next: number) => void, deps: unknown[]) {
  const setOffsetRef = useRef(setOffset)
  useEffect(() => {
    setOffsetRef.current = setOffset
  }, [setOffset])

  // Ключ зависимостей: меняется только при реальной смене поиска/фильтров.
  const key = JSON.stringify(deps)
  const prevKey = useRef<string | null>(null)
  useEffect(() => {
    if (prevKey.current === null || prevKey.current === key) {
      prevKey.current = key
      return
    }
    prevKey.current = key
    setOffsetRef.current(0)
  }, [key])
}

/** Смещение (offset) списка, синхронизированное с URL (`?offset=`). */
export function useOffset(): [number, (next: number) => void] {
  const [params, setParams] = useSearchParams()
  const raw = Number(params.get('offset') ?? 0)
  const offset = Number.isFinite(raw) && raw > 0 ? raw : 0

  const setOffset = useCallback(
    (next: number) => {
      setParams(
        (prev) => {
          const nextParams = new URLSearchParams(prev)
          if (next <= 0) nextParams.delete('offset')
          else nextParams.set('offset', String(next))
          return nextParams
        },
        { replace: true },
      )
    },
    [setParams],
  )

  return [offset, setOffset]
}
