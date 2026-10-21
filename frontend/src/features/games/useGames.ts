import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  getGame,
  listGames,
  listGamesCovers,
  listGamesFilterOptions,
  listGameStreams,
  updateGameState,
} from '@/features/games/api'
import type { ListParams } from '@/features/games/api'
import type { GameDetail, GameView } from '@/api/types'

/** Список игр с серверными поиском, фильтрами, сортировкой и пагинацией. */
export function useGamesList(params: ListParams) {
  return useQuery({
    queryKey: ['games', 'list', params],
    queryFn: () => listGames(params),
    placeholderData: (previous) => previous,
  })
}

/** Доступные значения тегов для меню фильтров. */
export function useGamesFilterOptions() {
  return useQuery({
    queryKey: ['games', 'filters'],
    queryFn: listGamesFilterOptions,
    staleTime: 60 * 60_000,
  })
}

/** Обложки всех игр — для полосы обложек в разделе «Стримы». */
export function useGamesCovers() {
  return useQuery({
    queryKey: ['games', 'covers'],
    queryFn: listGamesCovers,
    staleTime: 60 * 60_000,
  })
}

/** Догрузка стримов по игре (длинный список на странице игры). */
export function useGameStreams(
  gameId: number | null,
  params: { limit: number; offset: number },
  enabled: boolean,
) {
  return useQuery({
    queryKey: ['games', 'streams', gameId, params],
    queryFn: () => listGameStreams(gameId as number, params),
    enabled: enabled && gameId !== null,
    placeholderData: (previous) => previous,
  })
}

export function useGame(id: number) {
  return useQuery({
    queryKey: ['games', 'detail', id],
    queryFn: () => getGame(id),
    enabled: Number.isFinite(id),
  })
}

interface GameStateVariables {
  gameId: number
  liked: boolean
  completed: boolean
}

/**
 * Отметки «Понравилось» / «Пройдено».
 *
 * Бэкенд обновляет оба флага сразу, поэтому в мутацию передаются оба
 * текущих значения. Обновление оптимистичное: флаг меняется сразу, при
 * ошибке возвращается прежнее значение.
 */
export function useUpdateGameState() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ gameId, liked, completed }: GameStateVariables) =>
      updateGameState(gameId, { liked, completed }),
    onMutate: async (variables) => {
      await queryClient.cancelQueries({ queryKey: ['games'] })
      const previous = queryClient.getQueriesData<GameView[]>({
        queryKey: ['games', 'list'],
      })
      const previousDetail = queryClient.getQueryData<GameDetail>([
        'games',
        'detail',
        variables.gameId,
      ])
      // Список кешируется по параметрам — обновляем все его варианты.
      queryClient.setQueriesData<GameView[]>({ queryKey: ['games', 'list'] }, (old) =>
        old
          ? old.map((game) =>
              game.id === variables.gameId
                ? { ...game, liked: variables.liked, completed: variables.completed }
                : game,
            )
          : old,
      )
      queryClient.setQueryData<GameDetail>(
        ['games', 'detail', variables.gameId],
        (old) =>
          old ? { ...old, liked: variables.liked, completed: variables.completed } : old,
      )
      return { previous, previousDetail }
    },
    onError: (error, variables, context) => {
      context?.previous?.forEach(([key, data]) => {
        queryClient.setQueryData(key, data)
      })
      if (context?.previousDetail) {
        queryClient.setQueryData(
          ['games', 'detail', variables.gameId],
          context.previousDetail,
        )
      }
      toast.error(error.message)
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ['games'] })
    },
  })
}
