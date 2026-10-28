import { api } from '@/api/client'
import type {
  StreamParticipantActionResult,
  StreamParticipantDeleteResult,
  StreamsPage,
} from '@/api/types'

export interface StreamsListParams {
  search?: string
  sort?: string
  direction?: 'asc' | 'desc'
  filters?: string[]
  date?: string
  limit: number
  offset: number
}

/** Список стримов: поиск, фильтры, сортировка и пагинация — на сервере. */
export function listStreams(params: StreamsListParams): Promise<StreamsPage> {
  return api.get<StreamsPage>('/streams', { params }).then((response) => response.data)
}

export interface StreamParticipantFilter {
  login: string
  label: string
}

export interface StreamsFilterOptions {
  tags: string[]
  dates: string[]
  participants: StreamParticipantFilter[]
}

/** Доступные значения тегов, дат и участников — для меню фильтров. */
export function listStreamsFilterOptions(): Promise<StreamsFilterOptions> {
  return api
    .get<StreamsFilterOptions>('/streams/filters')
    .then((response) => response.data)
}

/** Добавить участника на стрим по логину Twitch. */
export function addStreamParticipant(
  streamId: number,
  userLogin: string,
): Promise<StreamParticipantActionResult> {
  return api
    .post<StreamParticipantActionResult>(`/streams/${streamId}/participants`, {
      user_login: userLogin,
    })
    .then((response) => response.data)
}

/** Удалить участника со стрима. */
export function deleteStreamParticipant(
  streamId: number,
  userId: number,
): Promise<StreamParticipantDeleteResult> {
  return api
    .delete<StreamParticipantDeleteResult>(
      `/streams/${streamId}/participants/${userId}`,
    )
    .then((response) => response.data)
}
