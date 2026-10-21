import { api } from '@/api/client'
import type { StreamsPage } from '@/api/types'

export interface StreamsListParams {
  search?: string
  sort?: string
  direction?: 'asc' | 'desc'
  filters?: string[]
  date?: string
  limit: number
  offset: number
}

/** Список стримов: поиск, фильтры, сортировка и пагинация — на сервере. */
export function listStreams(params: StreamsListParams): Promise<StreamsPage> {
  return api.get<StreamsPage>('/streams', { params }).then((response) => response.data)
}

/** Доступные значения тегов и дат — для меню фильтров. */
export function listStreamsFilterOptions(): Promise<{ tags: string[]; dates: string[] }> {
  return api
    .get<{ tags: string[]; dates: string[] }>('/streams/filters')
    .then((response) => response.data)
}
