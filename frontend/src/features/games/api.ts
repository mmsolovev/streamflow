import { api } from '@/api/client'
import type {
  GameDetail,
  GamesPage,
  GameReviewLink,
  CurrentStreamGame,
  GameIGDBRefreshBody,
  GameIGDBRefreshResult,
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

/** Игры стрима, которые ещё не вошли в агрегированную статистику. */
export function listCurrentStreamGames(): Promise<CurrentStreamGame[]> {
  return api
    .get<CurrentStreamGame[]>('/games/current-stream')
    .then((response) => response.data)
}

/** Обновить IGDB metadata игры по ID или ссылке на IGDB. */
export function refreshGameIGDB(
  gameId: number,
  body: GameIGDBRefreshBody,
): Promise<GameIGDBRefreshResult> {
  return api
    .post<GameIGDBRefreshResult>(`/games/${gameId}/refresh-igdb`, body)
    .then((response) => response.data)
}

export async function setGameCoverUrl(gameId: number, url: string) {
  const { data } = await api.put<{ game_id: number; cover_url: string }>(
    `/games/${gameId}/cover/url`,
    { url },
  )
  return data
}

export async function uploadGameCover(gameId: number, file: File) {
  const form = new FormData()
  form.append('file', file)
  const { data } = await api.post<{ game_id: number; cover_url: string }>(
    `/games/${gameId}/cover/file`,
    form,
  )
  return data
}

export async function deleteGameCover(gameId: number): Promise<void> {
  await api.delete(`/games/${gameId}/cover`)
}

export async function updateGameIGDBId(gameId: number, igdbId: string | null) {
  const { data } = await api.patch<{
    game_id: number
    igdb_id: string | null
    message: string
  }>(`/games/${gameId}/igdb-id`, { igdb_id: igdbId })
  return data
}

/** Установить полный список ссылок на отзывы/клипы игры. */
export async function updateGameReviews(
  gameId: number,
  links: GameReviewLink[],
): Promise<{ game_id: number; links: GameReviewLink[] }> {
  const { data } = await api.patch<{ game_id: number; links: GameReviewLink[] }>(
    `/games/${gameId}/reviews`,
    { links },
  )
  return data
}
