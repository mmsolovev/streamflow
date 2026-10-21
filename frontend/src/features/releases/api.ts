import { api } from '@/api/client'
import type { InterestUpdateResult, ReleasesPage } from '@/api/types'

export interface ReleasesListParams {
  search?: string
  sort?: string
  direction?: 'asc' | 'desc'
  filters?: string[]
  limit: number
  offset: number
}

/** Список релизов: поиск, фильтры, сортировка и пагинация — на сервере. */
export function listReleases(params: ReleasesListParams): Promise<ReleasesPage> {
  return api.get<ReleasesPage>('/releases', { params }).then((response) => response.data)
}

/** Отметка «Интересно» (доступно только админу). */
export async function setReleaseInterested(
  gameId: number,
  interested: boolean,
): Promise<InterestUpdateResult> {
  const { data } = await api.patch<InterestUpdateResult>(
    `/releases/${gameId}/interested`,
    { interested },
  )
  return data
}

/** Доступные значения фильтров: теги, платформы, рекомендовавшие. */
export function listReleasesFilterOptions(): Promise<{
  tags: string[]
  platforms: string[]
  recommenders: Array<{ login: string; label: string }>
}> {
  return api
    .get<{
      tags: string[]
      platforms: string[]
      recommenders: Array<{ login: string; label: string }>
    }>('/releases/filters')
    .then((response) => response.data)
}
