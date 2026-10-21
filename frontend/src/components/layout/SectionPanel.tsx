import { NavLink } from 'react-router-dom'

import { ChannelAvatar } from '@/components/layout/ChannelAvatar'
import { STATS_TABS } from '@/config/nav'
import { cn } from '@/lib/cn'

/** Левая панель вкладки «Статистика» (на узких экранах скрывается). */
export function SectionPanel() {
  return (
    <aside className="hidden w-44 shrink-0 border-r md:block [border-color:color-mix(in_srgb,var(--accent)_20%,transparent)]">
      {/* Аватар канала — из profile_image_url (Twitch CDN). */}
      <ChannelAvatar />
      {/* Список навигации — фиксируется при прокрутке и отступает от аватара. */}
      <nav className="sticky top-14 flex flex-col gap-1 p-3">
        {STATS_TABS.map((tab) => (
          <NavLink
            key={tab.key}
            to={tab.to}
            className={({ isActive }) =>
              cn(
                'rounded-md px-3 py-2 text-sm uppercase tracking-wider transition-colors',
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
    </aside>
  )
}
