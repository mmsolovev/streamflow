import { NavLink, useLocation } from 'react-router-dom'

import { ChannelAvatar } from '@/components/layout/ChannelAvatar'
import { BOT_TABS, STATS_TABS } from '@/config/nav'
import { cn } from '@/lib/cn'

/** Левая панель вкладки (на узких экранах скрывается). */
export function SectionPanel() {
  const location = useLocation()
  const isBot = location.pathname.startsWith('/bot')
  const tabs = isBot ? BOT_TABS : STATS_TABS

  return (
    <aside className="hidden w-44 shrink-0 flex-col border-r md:flex [border-color:color-mix(in_srgb,var(--accent)_20%,transparent)]">
      <div>
        {/* Аватар канала — из profile_image_url (Twitch CDN). */}
        <ChannelAvatar />
        {/* Список навигации — фиксируется при прокрутке и отступает от аватара. */}
        <nav className="sticky top-14 flex flex-col gap-1 p-3">
          {tabs.map((tab) => (
            <NavLink
              key={tab.key}
              to={tab.to}
              className={({ isActive }) =>
                cn(
                  'rounded-md px-3 py-2 text-sm uppercase tracking-wider transition-colors',
                  (tab as any).noUppercase && 'normal-case',
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
      </div>

      {/* Юридическая ссылка — в левом нижнем углу панели. */}
      <div className="sticky bottom-0 mt-auto bg-[var(--section-bg)] p-3">
        <NavLink
          to="/privacy"
          className={({ isActive }) =>
            cn(
              'block text-xs leading-snug transition-colors',
              isActive
                ? 'text-[var(--accent)]'
                : 'text-[var(--text-muted)] hover:text-[var(--text)]',
            )
          }
        >
          Политика конфиденциальности
        </NavLink>
      </div>
    </aside>
  )
}
