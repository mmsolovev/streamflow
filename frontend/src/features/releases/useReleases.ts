import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  listReleases,
  listReleasesFilterOptions,
  setReleaseInterested,
} from '@/features/releases/api'
import type { ReleasesListParams } from '@/features/releases/api'
import type { ReleasesPage } from '@/api/types'

/** Список релизов с серверными поиском, фильтрами, сортировкой и пагинацией. */
export function useReleasesList(params: ReleasesListParams) {
  return useQuery({
    queryKey: ['releases', 'list', params],
    queryFn: () => listReleases(params),
    placeholderData: (previous) => previous,
  })
}

/** Доступные значения фильтров для меню. */
export function useReleasesFilterOptions() {
  return useQuery({
    queryKey: ['releases', 'filters'],
    queryFn: listReleasesFilterOptions,
    staleTime: 60 * 60_000,
  })
}

/** Отметка «Интересно» (обновление оптимистичное). */
export function useSetReleaseInterested() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ gameId, interested }: { gameId: number; interested: boolean }) =>
      setReleaseInterested(gameId, interested),
    onMutate: async (variables) => {
      await queryClient.cancelQueries({ queryKey: ['releases'] })
      const previous = queryClient.getQueriesData<ReleasesPage>({
        queryKey: ['releases', 'list'],
      })
      queryClient.setQueriesData<ReleasesPage>(
        { queryKey: ['releases', 'list'] },
        (old) =>
          old
            ? {
                ...old,
                items: old.items.map((release) =>
                  release.id === variables.gameId
                    ? { ...release, interested: variables.interested }
                    : release,
                ),
              }
            : old,
      )
      return { previous }
    },
    onError: (error, _variables, context) => {
      context?.previous?.forEach(([key, data]) => {
        queryClient.setQueryData(key, data)
      })
      toast.error(error.message)
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ['releases'] })
      void queryClient.invalidateQueries({ queryKey: ['recommendations'] })
    },
  })
}
