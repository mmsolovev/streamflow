import { QueryClient } from '@tanstack/react-query'

import { ApiError } from '@/lib/apiError'

/**
 * Общий QueryClient.
 * - не тянем данные заново при фокусе окна;
 * - ошибки 4xx не ретраим, 5xx/сеть — до 2 раз.
 */
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      retry: (failureCount, error) => {
        if (error instanceof ApiError && error.status && error.status < 500) {
          return false
        }
        return failureCount < 2
      },
    },
    mutations: {
      retry: false,
    },
  },
})
