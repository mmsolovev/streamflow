import { api } from '@/api/client'
import type { ClipsPage, MediaFilterOptions, RecordingsPage } from '@/api/types'

export type ClipPeriod = 'day' | 'week' | 'month' | 'all'
export type MediaSort = 'date' | 'views' | 'title' | 'duration'

export interface MediaListParams {
  search?: string
  sort: MediaSort
  direction: 'asc' | 'desc'
  limit: number
  offset: number
  period?: ClipPeriod
  filters?: string[]
}

export function listRecordings(params: MediaListParams): Promise<RecordingsPage> {
  return api
    .get<RecordingsPage>('/media/recordings', { params })
    .then((response) => response.data)
}

export function listClips(params: MediaListParams): Promise<ClipsPage> {
  return api
    .get<ClipsPage>('/media/clips', { params })
    .then((response) => response.data)
}

export function listMediaFilterOptions(
  section: 'recordings' | 'clips',
): Promise<MediaFilterOptions> {
  return api
    .get<MediaFilterOptions>('/media/filters', { params: { section } })
    .then((response) => response.data)
}

export interface RecordingPreviewResult {
  recording_id: number
  thumbnail_url: string | null
  message: string
}

export function setRecordingPreviewUrl(
  recordingId: number,
  url: string,
): Promise<RecordingPreviewResult> {
  return api
    .put<RecordingPreviewResult>(
      `/media/recordings/${recordingId}/preview/url`,
      { url },
    )
    .then((response) => response.data)
}

export function uploadRecordingPreview(
  recordingId: number,
  file: File,
): Promise<RecordingPreviewResult> {
  const form = new FormData()
  form.append('file', file)
  return api
    .post<RecordingPreviewResult>(
      `/media/recordings/${recordingId}/preview/file`,
      form,
    )
    .then((response) => response.data)
}

export async function deleteRecordingPreview(recordingId: number): Promise<void> {
  await api.delete(`/media/recordings/${recordingId}/preview`)
}
