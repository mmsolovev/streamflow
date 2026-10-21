import { api } from '@/api/client'
import type {
  GameDetail,
  GamesPage,
  GameStateUpdateBody,
  GameStateUpdateResult,
  GameStreamsPage,
} from '@/api/types'

export interface ListParams {
  search?: string
  sort?: string
  direction?: 'asc' | 'desc'
  filters?: string[]
  limit: number
  offset: number
}

/** Список игр: поиск, фильтры, сортировка и пагинация — на сервере. */
export function listGames(params: ListParams): Promise<GamesPage> {
  return api.get<GamesPage>('/games', { params }).then((response) => response.data)
}

/** Доступные значения тегов — для меню фильтров. */
export function listGamesFilterOptions(): Promise<{
  tags: string[]
  platforms: string[]
}> {
  return api
    .get<{ tags: string[]; platforms: string[] }>('/games/filters')
    .then((response) => response.data)
}

/** Имя → обложка игры (для полосы обложек в разделе «Стримы»). */
export function listGamesCovers(): Promise<
  Array<{ id: number; name: string; cover_url: string | null }>
> {
  return api
    .get<Array<{ id: number; name: string; cover_url: string | null }>>('/games/covers')
    .then((response) => response.data)
}

/** Стримы по игре — догрузка длинного списка на странице игры. */
export function listGameStreams(
  gameId: number,
  params: { limit: number; offset: number },
): Promise<GameStreamsPage> {
  return api
    .get<GameStreamsPage>(`/games/${gameId}/streams`, { params })
    .then((response) => response.data)
}

export async function getGame(id: number): Promise<GameDetail> {
  const { data } = await api.get<GameDetail>(`/games/${id}`)
  return data
}

/** Отметки «Понравилось» / «Пройдено» (доступно только админу). */
export async function updateGameState(
  gameId: number,
  body: GameStateUpdateBody,
): Promise<GameStateUpdateResult> {
  const { data } = await api.patch<GameStateUpdateResult>(
    `/games/${gameId}/streamer-state`,
    body,
  )
  return data
}
