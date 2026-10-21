import { api } from '@/api/client'
import type {
  RecommendationActionResult,
  RecommendationAddBody,
  RecommendationDeleteResult,
  RecommendationSearchOut,
  RecommendationsPage,
} from '@/api/types'

export interface RecommendationsListParams {
  search?: string
  sort?: string
  direction?: 'asc' | 'desc'
  filters?: string[]
  limit: number
  offset: number
}

/** Список советов: поиск, фильтры, сортировка и пагинация — на сервере. */
export function listRecommendations(
  params: RecommendationsListParams,
): Promise<RecommendationsPage> {
  return api
    .get<RecommendationsPage>('/recommendations', { params })
    .then((response) => response.data)
}

/** Доступные значения фильтров: теги, платформы, рекомендовавшие. */
export function listRecommendationsFilterOptions(): Promise<{
  tags: string[]
  platforms: string[]
  recommenders: Array<{ login: string; label: string }>
}> {
  return api
    .get<{
      tags: string[]
      platforms: string[]
      recommenders: Array<{ login: string; label: string }>
    }>('/recommendations/filters')
    .then((response) => response.data)
}

/** Варианты игр для окна «Предложить игру» (поиск по IGDB). */
export function searchRecommendationCandidates(
  query: string,
): Promise<RecommendationSearchOut> {
  return api
    .get<RecommendationSearchOut>('/recommendations/search', { params: { q: query } })
    .then((response) => response.data)
}

/** Добавить рекомендацию (от себя или от имени другого пользователя). */
export function addRecommendation(
  query: string,
  igdbId?: string,
  note?: string,
  userLogin?: string,
): Promise<RecommendationActionResult> {
  const body: RecommendationAddBody = {
    query,
    igdb_id: igdbId ?? null,
    note: note ?? null,
    user_login: userLogin ?? null,
  }
  return api
    .post<RecommendationActionResult>('/recommendations', body)
    .then((response) => response.data)
}

/** Удалить рекомендацию (свою или чужую — для админа). */
export function deleteRecommendation(
  gameId: number,
  login?: string,
): Promise<RecommendationDeleteResult> {
  return api
    .delete<RecommendationDeleteResult>(`/recommendations/${gameId}`, {
      params: login ? { user_login: login } : undefined,
    })
    .then((response) => response.data)
}
