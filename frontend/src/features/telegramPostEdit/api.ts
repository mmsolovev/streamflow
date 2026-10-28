import { api } from '@/api/client'
import type {
  ActionAccepted,
  PostEditSettings,
  PostStreamState,
  VodCheckResult,
} from './types'

const BASE = '/admin/telegram/post-stream'

export function getPostStream(runId?: number | null): Promise<PostStreamState> {
  return api
    .get<PostStreamState>(BASE, { params: { run_id: runId ?? undefined } })
    .then((response) => response.data)
}

export function updateSettings(
  patch: Partial<PostEditSettings>,
): Promise<PostEditSettings> {
  return api
    .patch<PostEditSettings>(`${BASE}/settings`, patch)
    .then((response) => response.data)
}

export function resetSettings(): Promise<PostEditSettings> {
  return api
    .post<PostEditSettings>(`${BASE}/settings/reset`)
    .then((response) => response.data)
}

export function selectTarget(
  runId: number,
  announcementId: number,
): Promise<ActionAccepted> {
  return api
    .put<ActionAccepted>(`${BASE}/target`, {
      run_id: runId,
      announcement_id: announcementId,
    })
    .then((response) => response.data)
}

export function publishNow(runId: number): Promise<ActionAccepted> {
  return api
    .post<ActionAccepted>(`${BASE}/publish`, { run_id: runId })
    .then((response) => response.data)
}

export function undoEdit(runId: number): Promise<ActionAccepted> {
  return api
    .post<ActionAccepted>(`${BASE}/undo`, { run_id: runId })
    .then((response) => response.data)
}

export function restoreOriginal(runId: number): Promise<ActionAccepted> {
  return api
    .post<ActionAccepted>(`${BASE}/restore`, { run_id: runId })
    .then((response) => response.data)
}

export function checkVod(runId: number): Promise<VodCheckResult> {
  return api
    .post<VodCheckResult>(`${BASE}/check-vod`, { run_id: runId })
    .then((response) => response.data)
}
