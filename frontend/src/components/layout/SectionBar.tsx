import { NavLink } from 'react-router-dom'

import { STATS_TABS } from '@/config/nav'
import { cn } from '@/lib/cn'

/**
 * Переключатель разделов для узких экранов — горизонтальная лента вместо
 * боковой панели.
 */
export function SectionBar() {
  return (
    <nav className="flex gap-1 overflow-x-auto border-b border-white/10 px-3 py-2 md:hidden">
      {STATS_TABS.map((tab) => (
        <NavLink
          key={tab.key}
          to={tab.to}
          className={({ isActive }) =>
            cn(
              'shrink-0 rounded-md px-3 py-1.5 text-xs uppercase tracking-wider transition-colors',
              tab.noUppercase && 'normal-case',
              isActive
                ? 'text-[var(--accent)] [background:color-mix(in_srgb,var(--accent)_15%,transparent)]'
                : 'text-[var(--text)] hover:opacity-80',
            )
          }
        >
          {tab.label}
        </NavLink>
      ))}
    </nav>
  )
}
