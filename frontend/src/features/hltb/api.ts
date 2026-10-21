import { api } from '@/api/client'
import type { HltbAddResult, HltbLookup, HltbPage } from '@/api/types'

export interface HltbListParams {
  search?: string
  sort?: string
  direction?: 'asc' | 'desc'
  limit: number
  offset: number
}

/** Список HLTB: поиск, сортировка и пагинация — на сервере. */
export function listHltb(params: HltbListParams): Promise<HltbPage> {
  return api.get<HltbPage>('/hltb', { params }).then((response) => response.data)
}

/** Ищет игру по ссылке HowLongToBeat (предпросмотр перед добавлением). */
export async function lookupHltb(url: string): Promise<HltbLookup> {
  const { data } = await api.post<HltbLookup>('/hltb/lookup', { url })
  return data
}

/** Добавляет игру по ссылке HowLongToBeat (HLTB + обновление IGDB). */
export async function addHltb(
  url: string,
  gameId?: number | null,
): Promise<HltbAddResult> {
  const { data } = await api.post<HltbAddResult>('/hltb', {
    url,
    game_id: gameId ?? null,
  })
  return data
}
