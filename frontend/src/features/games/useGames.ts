import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  getGame,
  listGames,
  listCurrentStreamGames,
  listGamesCovers,
  listGamesFilterOptions,
  listGameStreams,
  refreshGameIGDB,
  updateGameReviews,
  updateGameState,
} from '@/features/games/api'
import type { ListParams } from '@/features/games/api'
import type {
  GameDetail,
  GameIGDBRefreshBody,
  GameIGDBRefreshResult,
  GamesPage,
} from '@/api/types'
import type { GameReviewLink } from '@/api/types'

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
      const previous = queryClient.getQueriesData<GamesPage>({
        queryKey: ['games', 'list'],
      })
      const previousDetail = queryClient.getQueryData<GameDetail>([
        'games',
        'detail',
        variables.gameId,
      ])
      // Список кешируется по параметрам — обновляем все его варианты.
      queryClient.setQueriesData<GamesPage>({ queryKey: ['games', 'list'] }, (old) =>
        old
          ? {
              ...old,
              items: old.items.map((game) =>
                game.id === variables.gameId
                  ? {
                      ...game,
                      liked: variables.liked,
                      completed: variables.completed,
                    }
                  : game,
              ),
            }
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

/** Live-игры и завершённые игры, пока ждёт агрегатор статистики. */
export function useCurrentStreamGames() {
  return useQuery({
    queryKey: ['games', 'current-stream'],
    queryFn: listCurrentStreamGames,
    refetchInterval: 15_000,
    refetchIntervalInBackground: false,
  })
}

export function useUpdateGameReviews() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ gameId, links }: { gameId: number; links: GameReviewLink[] }) =>
      updateGameReviews(gameId, links),
    onSuccess: () => toast.success('Ссылки на отзывы сохранены.'),
    onError: (error) => toast.error(error.message),
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ['games'] })
    },
  })
}

export function useRefreshGameIGDB() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      gameId,
      body,
    }: {
      gameId: number
      body: GameIGDBRefreshBody
    }): Promise<GameIGDBRefreshResult> => refreshGameIGDB(gameId, body),
    onSuccess: (result) => {
      toast.success(result.message)
      void queryClient.invalidateQueries({ queryKey: ['games'] })
      void queryClient.invalidateQueries({ queryKey: ['releases'] })
      void queryClient.invalidateQueries({ queryKey: ['recommendations'] })
    },
    onError: (error) => toast.error(error.message),
  })
}
