import { useMemo, useState } from 'react'
import { Plus } from 'lucide-react'

import { SectionHeader } from '@/components/layout/SectionHeader'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { SearchInput } from '@/components/ui/SearchInput'
import { TableSkeleton } from '@/components/ui/Skeleton'
import { cn } from '@/lib/cn'
import { useAuth } from '@/features/auth/context'
import { AddBotCommandModal } from '@/features/bot/AddBotCommandModal'

interface BotCommandRow {
  id: number
  botName: string
  name: string
  description: string
  access: string
  isExternal: boolean
}

const MOCK_COMMANDS: BotCommandRow[] = [
  {
    id: 1,
    botName: 'self',
    name: '!игры',
    description: 'Статистика по игре',
    access: 'все',
    isExternal: false,
  },
  {
    id: 2,
    botName: 'self',
    name: '!рек',
    description: 'Рекомендация/голос; управление рекомендациями',
    access: 'все',
    isExternal: false,
  },
  {
    id: 3,
    botName: 'self',
    name: '!фильм',
    description: 'Текущий фильм; управление для админов',
    access: 'все',
    isExternal: false,
  },
  {
    id: 4,
    botName: 'self',
    name: '!команды',
    description: 'Справка по командам',
    access: 'все',
    isExternal: false,
  },
  {
    id: 5,
    botName: 'StreamElements',
    name: '!points',
    description: 'Просмотр баллов',
    access: 'все',
    isExternal: true,
  },
]

function groupByBot(rows: BotCommandRow[]) {
  const groups: Record<string, BotCommandRow[]> = {}
  for (const row of rows) {
    if (!groups[row.botName]) groups[row.botName] = []
    groups[row.botName].push(row)
  }
  return groups
}

export function BotCommandsView() {
  const { isAuthenticated } = useAuth()
  const [search, setSearch] = useState('')
  const [openAdd, setOpenAdd] = useState(false)

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return MOCK_COMMANDS
    return MOCK_COMMANDS.filter(
      (r) =>
        r.name.toLowerCase().includes(q) ||
        r.description.toLowerCase().includes(q) ||
        r.botName.toLowerCase().includes(q),
    )
  }, [search])

  const groups = useMemo(() => groupByBot(filtered), [filtered])
  const botNames = Object.keys(groups).sort((a, b) => (a === 'self' ? -1 : b === 'self' ? 1 : a.localeCompare(b)))
  const total = filtered.length

  return (
    <div className="flex flex-1 flex-col" data-section="commands">
      <SectionHeader
        title="Команды"
        subtitle={`Показано ${total} команд`}
        hint={
          <>
            Информация о команде{' '}
            <span className="font-social text-[var(--accent)]">!команды</span>
          </>
        }
        action={
          <button
            type="button"
            onClick={() => setOpenAdd(true)}
            className={cn(
              'flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition-colors',
              isAuthenticated
                ? 'bg-[var(--accent)] font-medium text-black hover:opacity-90'
                : 'border border-[var(--accent)] text-[var(--accent)] hover:opacity-80',
            )}
          >
            <Plus className="h-4 w-4" />
            Добавить команду
          </button>
        }
      >
        <SearchInput
          value={search}
          onChange={setSearch}
          placeholder="Поиск по командам..."
          className="w-full sm:w-80"
        />
      </SectionHeader>

      <div className="flex flex-1 flex-col gap-4 p-6" style={{ background: '#18171F' }}>
        {botNames.length === 0 ? (
          <EmptyState hint="Команды не найдены." />
        ) : (
          botNames.map((botName) => (
            <div
              key={botName}
              className="overflow-hidden rounded-lg border"
              style={{ background: '#24212E', borderColor: 'rgba(169, 112, 255, 0.3)' }}
            >
              <div
                className="flex items-center gap-2 border-b px-4 py-2"
                style={{ borderColor: 'rgba(169, 112, 255, 0.2)' }}
              >
                <div
                  className="h-2 w-2 rounded-full"
                  style={{ background: '#A970FF' }}
                />
                <span className="text-sm font-medium uppercase tracking-wide" style={{ color: '#A970FF' }}>
                  {botName === 'self' ? 'Mishgan Bot' : botName}
                </span>
                <span className="text-xs text-[var(--text-muted)]">
                  {groups[botName].length}
                </span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b" style={{ borderColor: 'rgba(169, 112, 255, 0.15)' }}>
                      <th className="px-4 py-2 text-left text-xs uppercase tracking-wide text-[var(--text-muted)]">
                        Команда
                      </th>
                      <th className="px-4 py-2 text-left text-xs uppercase tracking-wide text-[var(--text-muted)]">
                        Описание
                      </th>
                      <th className="px-4 py-2 text-left text-xs uppercase tracking-wide text-[var(--text-muted)]">
                        Доступ
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {groups[botName].map((cmd) => (
                      <tr
                        key={cmd.id}
                        className="border-b transition-colors hover:bg-white/[0.02]"
                        style={{ borderColor: 'rgba(169, 112, 255, 0.1)' }}
                      >
                        <td className="px-4 py-2 font-social text-[var(--accent)]">{cmd.name}</td>
                        <td className="px-4 py-2 text-[var(--text)]">{cmd.description}</td>
                        <td className="px-4 py-2 text-[var(--text-muted)]">{cmd.access}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ))
        )}
      </div>

      {openAdd ? <AddBotCommandModal open onClose={() => setOpenAdd(false)} /> : null}
    </div>
  )
}
