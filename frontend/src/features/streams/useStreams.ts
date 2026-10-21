import { useQuery } from '@tanstack/react-query'

import { listStreams, listStreamsFilterOptions } from '@/features/streams/api'
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
