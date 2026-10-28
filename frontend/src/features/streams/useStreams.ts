import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  addStreamParticipant,
  deleteStreamParticipant,
  listStreams,
  listStreamsFilterOptions,
} from '@/features/streams/api'
import type { StreamsListParams } from '@/features/streams/api'

/** Список стримов с серверными поиском, фильтрами, сортировкой и пагинацией. */
export function useStreamsList(params: StreamsListParams) {
  return useQuery({
    queryKey: ['streams', 'list', params],
    queryFn: () => listStreams(params),
    placeholderData: (previous) => previous,
  })
}

/** Доступные значения тегов для меню фильтров. */
export function useStreamsFilterOptions() {
  return useQuery({
    queryKey: ['streams', 'filters'],
    queryFn: listStreamsFilterOptions,
    staleTime: 60 * 60_000,
  })
}

/** Добавление участника на стрим. */
export function useAddStreamParticipant() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ streamId, login }: { streamId: number; login: string }) =>
      addStreamParticipant(streamId, login),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['streams'] })
    },
  })
}

/** Удаление участника со стрима. */
export function useDeleteStreamParticipant() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ streamId, userId }: { streamId: number; userId: number }) =>
      deleteStreamParticipant(streamId, userId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['streams'] })
    },
  })
}
