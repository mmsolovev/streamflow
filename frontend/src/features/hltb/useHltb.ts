import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { addHltb, listHltb, lookupHltb } from '@/features/hltb/api'
import type { HltbListParams } from '@/features/hltb/api'

/** Список HLTB с серверными поиском, сортировкой и пагинацией. */
export function useHltbList(params: HltbListParams) {
  return useQuery({
    queryKey: ['hltb', 'list', params],
    queryFn: () => listHltb(params),
    placeholderData: (previous) => previous,
  })
}

/** Поиск игры по ссылке HLTB — предпросмотр перед добавлением. */
export function useHltbLookup() {
  return useMutation({
    mutationFn: (url: string) => lookupHltb(url),
  })
}

/** Добавление игры по ссылке HLTB (данные HLTB + обновление IGDB). */
export function useAddHltb() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ url, gameId }: { url: string; gameId?: number | null }) =>
      addHltb(url, gameId),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ['hltb'] })
      toast.success(result.message)
    },
    onError: (error) => {
      toast.error(error.message)
    },
  })
}
