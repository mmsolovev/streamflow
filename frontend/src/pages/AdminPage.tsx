import { CheckCircle2, XCircle } from 'lucide-react'
import { NavLink, useSearchParams } from 'react-router-dom'

import { SectionHeader } from '@/components/layout/SectionHeader'
import { AdminPanel } from '@/components/layout/AdminPanel'
import { SwitchLine } from '@/components/ui/SwitchLine'
import { goToStreamerLogin } from '@/features/auth/api'
import { useAuth } from '@/features/auth/context'
import { useStreamerStatus } from '@/features/auth/useStreamerStatus'
import { TelegramPostStreamPanel } from '@/features/telegramPostEdit/TelegramPostStreamPanel'
import type { AdminSection, TelegramTab } from '@/config/nav'
import { ADMIN_TABS, DEFAULT_TELEGRAM_TAB, TELEGRAM_TABS } from '@/config/nav'
import { cn } from '@/lib/cn'
import { formatDateTime } from '@/lib/format'

const TITLES: Record<AdminSection, string> = {
  management: 'Управление',
  connections: 'Подключения',
  telegram: 'Telegram',
}

const NOTES: Record<AdminSection, string> = {
  management: 'Раздел управления ботом.',
  connections: 'Информация о подключенных сервисах.',
  telegram: 'Управление Telegram-ботом по ходу стрима',
}

/** Карточка сервиса Twitch: подключенные аккаунты и запрошенные разрешения. */
function TwitchServiceCard() {
  const { user } = useAuth()
  const status = useStreamerStatus()

  if (status.isLoading) {
    return <p className="text-sm text-[var(--text-muted)]">Загрузка…</p>
  }
  if (status.isError) {
    return <p className="text-sm text-red-400">{status.error.message}</p>
  }

  const scopes = status.data?.requested_scopes ?? []
  const streamers = status.data?.streamers ?? []
  const canConnect = Boolean(user?.is_streamer)

  return (
    <div className="overflow-hidden rounded-lg border border-white/10 bg-[var(--card-bg)]">
      <header className="flex flex-wrap items-center gap-3 border-b border-white/10 px-5 py-3">
        <h2 className="font-social text-sm uppercase tracking-wide text-[var(--text)]">
          Twitch
        </h2>
        <button
          type="button"
          onClick={goToStreamerLogin}
          disabled={!canConnect}
          className="ml-auto rounded-md bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-black transition-opacity enabled:hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          title={canConnect ? undefined : 'Доступно только аккаунту стримера'}
        >
          Подключить права
        </button>
      </header>

      <div className="space-y-5 px-5 py-4 text-sm">
        <div>
          <div className="mb-1.5 text-xs uppercase tracking-wide text-[var(--text-muted)]">
            Запрошенные разрешения
          </div>
          <div className="flex flex-wrap gap-1.5">
            {scopes.length ? (
              scopes.map((scope) => (
                <code
                  key={scope}
                  className="rounded bg-white/5 px-2 py-0.5 text-xs text-[var(--text)]"
                >
                  {scope}
                </code>
              ))
            ) : (
              <span className="text-[var(--text-muted)]">—</span>
            )}
          </div>
        </div>

        <div>
          <div className="mb-1.5 text-xs uppercase tracking-wide text-[var(--text-muted)]">
            Подключенные аккаунты
          </div>
          <table className="w-full text-left">
            <thead>
              <tr className="text-xs uppercase tracking-wide text-[var(--text-muted)]">
                <th className="py-2 pr-4 font-normal">Аккаунт</th>
                <th className="py-2 pr-4 font-normal">Статус</th>
                <th className="py-2 font-normal">Действует до</th>
              </tr>
            </thead>
            <tbody>
              {streamers.map((streamer) => (
                <tr key={streamer.login} className="border-t border-white/5">
                  <td className="py-2 pr-4 text-[var(--text)]">{streamer.login}</td>
                  <td className="py-2 pr-4">
                    {streamer.connected ? (
                      <span className="inline-flex items-center gap-1.5 text-[var(--accent)]">
                        <CheckCircle2 className="h-4 w-4" /> подключено
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1.5 text-[var(--text-muted)]">
                        <XCircle className="h-4 w-4" /> не подключено
                      </span>
                    )}
                  </td>
                  <td className="py-2 text-[var(--text-muted)]">
                    {streamer.connected ? formatDateTime(streamer.expires_at) : '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        <p className="text-xs text-[var(--text-muted)]">
          Токен нужен боту для операций, доступных только аккаунту стримера (например,
          управление баллами канала). Подключить может только аккаунт стримера.
        </p>
      </div>
    </div>
  )
}

/** Линия-переключатель подразделов раздела «Telegram» (на всю ширину). */
function TelegramSwitchLine() {
  const [searchParams, setSearchParams] = useSearchParams()
  const raw = searchParams.get('tab')
  const active: TelegramTab =
    TELEGRAM_TABS.find((tab) => tab.param === raw)?.key ?? DEFAULT_TELEGRAM_TAB

  return (
    <SwitchLine
      items={TELEGRAM_TABS.map((tab) => ({ key: tab.key, label: tab.label }))}
      activeKey={active}
      onSelect={(key) => {
        const tab = TELEGRAM_TABS.find((item) => item.key === key)
        if (!tab) return
        setSearchParams({ tab: tab.param }, { replace: false })
      }}
    />
  )
}

function TelegramContent() {
  const [searchParams] = useSearchParams()
  const raw = searchParams.get('tab')
  const active: TelegramTab =
    TELEGRAM_TABS.find((tab) => tab.param === raw)?.key ?? DEFAULT_TELEGRAM_TAB

  if (active === 'end') {
    return <TelegramPostStreamPanel />
  }

  return (
    <div className="flex-1 px-6 py-5">
      <p className="text-sm text-[var(--text-muted)]">Раздел в разработке.</p>
    </div>
  )
}

/** Админ-раздел: та же компоновка, что в «Статистике» — панель слева, шапка и
 *  содержимое справа. */
export function AdminPage({ section }: { section: AdminSection }) {
  const title = TITLES[section]
  const note = NOTES[section]

  return (
    // Палитра раздела: у Telegram своя (голубая).
    <div
      data-section={section === 'telegram' ? 'telegram' : 'admin'}
      className="flex flex-1 flex-col bg-[var(--section-bg)]"
    >
      <div className="flex flex-1">
        <AdminPanel />
        <div className="flex flex-1 flex-col">
          {/* На узких экранах разделы админки — горизонтальной лентой. */}
          <nav className="flex gap-1 overflow-x-auto border-b border-white/10 px-3 py-2 md:hidden">
            {ADMIN_TABS.map((tab) => (
              <NavLink
                key={tab.key}
                to={tab.to}
                className={({ isActive }) =>
                  cn(
                    'shrink-0 rounded-md px-3 py-1.5 text-xs uppercase tracking-wider transition-colors',
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
          <SectionHeader
            title={title}
            hint={note}
            plainTitle={section === 'telegram'}
            noUppercase={section === 'telegram'}
          />
          {section === 'telegram' ? <TelegramSwitchLine /> : null}
          {section === 'connections' ? (
            <div className="p-6">
              <TwitchServiceCard />
            </div>
          ) : section === 'telegram' ? (
            <TelegramContent />
          ) : (
            <div className="flex flex-1 items-center justify-center p-8 text-sm text-[var(--text-muted)]">
              Раздел в разработке.
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
