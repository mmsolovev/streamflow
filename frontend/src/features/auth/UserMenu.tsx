import { useEffect, useRef, useState } from 'react'
import { Bot, ChevronDown, LogOut } from 'lucide-react'

import { goToStreamerLogin, logout } from '@/features/auth/api'
import { useAuth } from '@/features/auth/context'
import type { UserView } from '@/api/types'
import { cn } from '@/lib/cn'

/** Человекочитаемые роли пользователя. */
function userRoles(user: UserView): string[] {
  const roles: string[] = []
  if (user.is_admin) roles.push('Администратор')
  if (user.is_streamer) roles.push('Стример')
  return roles.length ? roles : ['Зритель']
}

/** Никнейм с выпадающей панелью пользователя (роль, выход и т.п.). */
export function UserMenu({ user }: { user: UserView }) {
  const { refetch } = useAuth()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handlePointer = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false)
    }
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', handlePointer)
    document.addEventListener('keydown', handleKey)
    return () => {
      document.removeEventListener('mousedown', handlePointer)
      document.removeEventListener('keydown', handleKey)
    }
  }, [open])

  const name = user.display_name ?? user.login ?? 'Профиль'
  const roles = userRoles(user)

  async function handleLogout() {
    setOpen(false)
    await logout()
    refetch()
  }

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
        className="flex items-center gap-1.5 rounded-md px-2 py-1.5 text-sm text-[var(--text)] transition-colors hover:bg-white/5"
      >
        {name}
        <ChevronDown
          className={cn('h-4 w-4 transition-transform', open && 'rotate-180')}
        />
      </button>

      {open ? (
        <div className="absolute right-0 top-full z-50 mt-2 w-56 overflow-hidden rounded-lg border border-white/10 bg-[var(--card-bg)] shadow-xl shadow-black/40">
          <div className="border-b border-white/10 px-3.5 py-3">
            <div className="truncate text-sm font-medium text-[var(--text)]">{name}</div>
            {user.login && user.login !== name ? (
              <div className="truncate text-xs text-[var(--text-muted)]">
                @{user.login}
              </div>
            ) : null}
            <div className="mt-2 flex flex-wrap gap-1.5">
              {roles.map((role) => (
                <span
                  key={role}
                  className="rounded bg-white/10 px-1.5 py-0.5 text-xs text-[var(--text-muted)]"
                >
                  {role}
                </span>
              ))}
            </div>
          </div>

          <div className="p-1.5">
            <button
              type="button"
              onClick={() => {
                setOpen(false)
                goToStreamerLogin()
              }}
              disabled={!user.is_streamer}
              className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-sm text-[var(--text)] transition-colors enabled:hover:bg-white/5 disabled:cursor-not-allowed disabled:text-[var(--text-muted)] disabled:opacity-60"
              title={
                user.is_streamer
                  ? 'Подключить расширенные права стримера'
                  : 'Доступно только аккаунту стримера'
              }
            >
              <Bot className="h-4 w-4 text-[var(--text-muted)]" />
              Подключить права бота
            </button>
            <button
              type="button"
              onClick={handleLogout}
              className="flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-sm text-[var(--text)] transition-colors hover:bg-white/5"
            >
              <LogOut className="h-4 w-4 text-[var(--text-muted)]" />
              Выйти
            </button>
          </div>
        </div>
      ) : null}
    </div>
  )
}
