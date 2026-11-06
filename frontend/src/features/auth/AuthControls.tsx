import { LoginMenu } from '@/features/auth/LoginMenu'
import { useAuth } from '@/features/auth/context'
import { UserMenu } from '@/features/auth/UserMenu'

/** Блок входа/выхода для верхней полосы. */
export function AuthControls() {
  const { user, isLoading } = useAuth()

  if (isLoading) {
    return <span className="text-sm text-[var(--text-muted)]">…</span>
  }

  if (!user) {
    return <LoginMenu />
  }

  return <UserMenu user={user} />
}
