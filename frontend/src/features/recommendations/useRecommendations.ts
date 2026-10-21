import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  addRecommendation,
  deleteRecommendation,
  listRecommendations,
  listRecommendationsFilterOptions,
  searchRecommendationCandidates,
} from '@/features/recommendations/api'
import type { RecommendationsListParams } from '@/features/recommendations/api'

/** Список советов с серверными поиском, фильтрами, сортировкой и пагинацией. */
export function useRecommendationsList(params: RecommendationsListParams) {
  return useQuery({
    queryKey: ['recommendations', 'list', params],
    queryFn: () => listRecommendations(params),
    placeholderData: (previous) => previous,
  })
}

/** Доступные значения фильтров для меню. */
export function useRecommendationsFilterOptions() {
  return useQuery({
    queryKey: ['recommendations', 'filters'],
    queryFn: listRecommendationsFilterOptions,
    staleTime: 60 * 60_000,
  })
}

export function useSearchRecommendationCandidates(query: string) {
  return useQuery({
    queryKey: ['recommendations', 'search', query],
    queryFn: () => searchRecommendationCandidates(query),
    enabled: query.trim().length > 1,
    staleTime: 30_000,
  })
}

/** Инвалидирует списки советов и релизов после любой мутации. */
function useRecommendationsMutation<TVariables, TResult>(
  mutationFn: (variables: TVariables) => Promise<TResult>,
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['recommendations'] })
      // Игра могла попасть в «Релизы» — обновляем и этот список.
      void queryClient.invalidateQueries({ queryKey: ['releases'] })
    },
  })
}

export function useAddRecommendation() {
  return useRecommendationsMutation(
    ({
      query,
      igdbId,
      note,
      userLogin,
    }: {
      query: string
      igdbId?: string
      note?: string
      userLogin?: string
    }) => addRecommendation(query, igdbId, note, userLogin),
  )
}

export function useDeleteRecommendation() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ gameId, login }: { gameId: number; login?: string }) =>
      deleteRecommendation(gameId, login),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['recommendations'] })
      // В «Релизах» список рекомендовавших приходит из релизов.
      void queryClient.invalidateQueries({ queryKey: ['releases'] })
    },
  })
}
