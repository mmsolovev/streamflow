import type { Page, PageParams } from '@/types/api'

/** Верхняя граница `limit` на бэкенде. */
const MAX_LIMIT = 500

/**
 * Собирает все страницы в один массив, последовательно запрашивая
 * `limit=500` со смещением.
 *
 * Бэкендные list-эндпоинты поддерживают только `limit`/`offset` (фильтры по
 * разделам добавляются на клиенте), а объёмы данных невелики, поэтому для
 * корректной сортировки/поиска грузим всё целиком.
 */
export async function fetchAllPages<T>(
  fetchPage: (params: PageParams) => Promise<Page<T>>,
): Promise<T[]> {
  const first = await fetchPage({ limit: MAX_LIMIT, offset: 0 })
  const items = [...first.items]

  while (items.length < first.total) {
    const next = await fetchPage({ limit: MAX_LIMIT, offset: items.length })
    if (next.items.length === 0) break
    items.push(...next.items)
  }

  return items
}
