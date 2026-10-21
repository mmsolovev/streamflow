import { NavLink, useLocation } from 'react-router-dom'

import { ChannelMenu } from '@/components/layout/ChannelMenu'
import { NAV_TABS } from '@/config/nav'
import { AuthControls } from '@/features/auth/AuthControls'
import { useAuth } from '@/features/auth/context'
import { cn } from '@/lib/cn'

/** Глобальная верхняя полоса, единая для всех страниц. */
export function TopBar() {
  const { isAdmin } = useAuth()
  const { pathname } = useLocation()
  const tabs = NAV_TABS.filter((tab) => tab.enabled)

  return (
    <header className="sticky top-0 z-40 flex h-14 items-center bg-[var(--topbar-bg)] pr-2 sm:pr-4">
      {/* Левая колонка шириной с боковую панель: Tabula — по её центру. */}
      <div className="flex w-auto shrink-0 items-center justify-center px-2 sm:w-44 sm:px-0">
        <ChannelMenu />
      </div>

      {/* Группирующие вкладки начинаются после правой границы боковой панели. */}
      <nav className="flex min-w-0 items-center gap-1 overflow-x-auto pl-2">
        {tabs.map((tab) => {
          const isActive = tab.bases.some(
            (base) => pathname === base || pathname.startsWith(`${base}/`),
          )
          return (
            <NavLink
              key={tab.key}
              to={tab.to}
              className={cn(
                'shrink-0 rounded-md px-3 py-2 text-sm transition-colors',
                isActive
                  ? 'bg-white/10 text-[var(--text)]'
                  : 'text-[var(--text-muted)] hover:text-[var(--text)]',
              )}
            >
              {tab.label}
            </NavLink>
          )
        })}
      </nav>

      <div className="ml-auto flex shrink-0 items-center gap-2 sm:gap-4">
        {isAdmin ? (
          <NavLink
            to="/admin"
            className={({ isActive }) =>
              cn(
                'rounded-md px-3 py-2 text-sm transition-colors',
                isActive
                  ? 'bg-white/10 text-[var(--text)]'
                  : 'text-[var(--text-muted)] hover:text-[var(--text)]',
              )
            }
          >
            Админка
          </NavLink>
        ) : null}
        <AuthControls />
      </div>
    </header>
  )
}
