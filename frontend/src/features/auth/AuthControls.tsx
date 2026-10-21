import { goToLogin } from '@/features/auth/api'
import { useAuth } from '@/features/auth/context'
import { UserMenu } from '@/features/auth/UserMenu'

/** Блок входа/выхода для верхней полосы. */
export function AuthControls() {
  const { user, isLoading } = useAuth()

  if (isLoading) {
    return <span className="text-sm text-[var(--text-muted)]">…</span>
  }

  if (!user) {
    return (
      <button
        type="button"
        onClick={goToLogin}
        className="font-social text-sm tracking-wide text-[var(--accent)] transition-opacity hover:opacity-80"
      >
        Войти через Twitch
      </button>
    )
  }

  return <UserMenu user={user} />
}
