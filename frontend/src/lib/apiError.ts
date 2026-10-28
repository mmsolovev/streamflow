import axios from 'axios'

import type { ApiErrorEnvelope } from '@/types/api'

/**
 * Нормализованная ошибка API. `code` — из конверта бэкенда
 * (`{detail:{code,message}}`) или синтетический (`http_500`, `network_error`).
 */
export class ApiError extends Error {
  readonly code: string
  readonly status?: number

  constructor(code: string, message: string, status?: number) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.status = status
  }
}

/** Приводит любую ошибку (axios, network, прочее) к `ApiError`. */
export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error

  if (axios.isAxiosError(error)) {
    const status = error.response?.status
    const envelope = error.response?.data as ApiErrorEnvelope | undefined
    const detail = envelope?.detail
    if (detail?.code) {
      return new ApiError(detail.code, detail.message, status)
    }
    if (status) {
      return new ApiError(`http_${status}`, error.message, status)
    }
    return new ApiError('network_error', 'Нет связи с сервером.')
  }

  if (error instanceof Error) {
    return new ApiError('unknown_error', error.message)
  }

  return new ApiError('unknown_error', 'Неизвестная ошибка.')
}
