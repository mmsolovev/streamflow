import { useQuery } from '@tanstack/react-query'

import { getStreamerStatus } from '@/features/auth/api'
import { useAuth } from '@/features/auth/context'

/** Статус «стримерских» токенов. Запрашивается только админами. */
export function useStreamerStatus() {
  const { isAdmin } = useAuth()
  return useQuery({
    queryKey: ['auth', 'streamer-status'],
    queryFn: getStreamerStatus,
    enabled: isAdmin,
    staleTime: 30_000,
  })
}
