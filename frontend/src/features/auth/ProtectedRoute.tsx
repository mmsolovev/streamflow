import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'

import { useAuth } from '@/features/auth/context'

/** Пропускает только авторизованных (и, при need, админов). */
export function ProtectedRoute({
  requireAdmin,
  children,
}: {
  requireAdmin?: boolean
  children: ReactNode
}) {
  const { isLoading, isAuthenticated, isAdmin } = useAuth()
  const location = useLocation()

  if (isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center p-8 text-[var(--text-muted)]">
        Проверка доступа…
      </div>
    )
  }

  if (!isAuthenticated) {
    return <Navigate to="/" state={{ from: location.pathname }} replace />
  }

  if (requireAdmin && !isAdmin) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-2 p-8">
        <h1 className="font-social text-xl text-[var(--text)]">Доступ закрыт</h1>
        <p className="text-sm text-[var(--text-muted)]">
          Раздел доступен только администраторам.
        </p>
      </div>
    )
  }

  return <>{children}</>
}
