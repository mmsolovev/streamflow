import { useCallback, useEffect, useMemo } from 'react'
import type { ReactNode } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import { getCurrentUser } from '@/features/auth/api'
import { AuthContext } from '@/features/auth/context'
import type { AuthValue } from '@/features/auth/context'

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: ['auth', 'me'],
    queryFn: getCurrentUser,
    staleTime: 5 * 60_000,
  })

  const refetch = useCallback(() => {
    void query.refetch()
  }, [query])

  // После возврата с OAuth-редиректа обновляем пользователя/статус и убираем
  // параметр из адреса: `login=success` — обычный вход, `streamer=...` —
  // подключение расширенных прав стримера.
  useEffect(() => {
    const url = new URL(window.location.href)
    const login = url.searchParams.get('login')
    const streamer = url.searchParams.get('streamer')
    if (!login && !streamer) return
    url.searchParams.delete('login')
    url.searchParams.delete('streamer')
    window.history.replaceState({}, '', url.toString())
    void query.refetch()
    if (streamer === 'success') {
      toast.success('Расширенные права стримера подключены.')
      void queryClient.invalidateQueries({ queryKey: ['auth', 'streamer-status'] })
    } else if (streamer === 'denied') {
      toast.error('Этот аккаунт не имеет доступа к расширенным правам стримера.')
    }
  }, [query, queryClient])

  const value = useMemo<AuthValue>(() => {
    const user = query.data ?? null
    const capabilities = new Set(user?.capabilities ?? [])
    return {
      user,
      isLoading: query.isLoading,
      isAuthenticated: user !== null,
      isStreamer: user?.role === 'streamer',
      isAdmin: capabilities.has('admin_commands'),
      canEdit: capabilities.has('edit_tables') && Boolean(user?.can_write),
      refetch,
    }
  }, [query.data, query.isLoading, refetch])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
