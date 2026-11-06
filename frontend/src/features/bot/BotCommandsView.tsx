import { useMemo, useState } from 'react'
import { Plus } from 'lucide-react'

import type { BotCommandView } from '@/api/types'
import { EntityList } from '@/components/entity/EntityList'
import type { EntityColumn } from '@/components/entity/types'
import { SectionHeader } from '@/components/layout/SectionHeader'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { FlagToggle } from '@/components/ui/FlagToggle'
import { Pagination } from '@/components/ui/Pagination'
import { SearchInput } from '@/components/ui/SearchInput'
import { TableSkeleton } from '@/components/ui/Skeleton'
import { StatChip } from '@/components/ui/StatChip'
import { useAuth } from '@/features/auth/context'
import { AddBotCommandModal } from '@/features/bot/AddBotCommandModal'
import {
  useBotCommandsList,
  useUpdateBotCommandState,
} from '@/features/bot/useBotCommands'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { useOffset, useResetOffsetOn } from '@/hooks/useOffset'
import { useTableSort } from '@/hooks/useTableSort'
import { formatNumber } from '@/lib/format'

const PAGE_SIZE = 50

const GRID = `minmax(120px, 0.7fr) minmax(340px, 3.4fr) minmax(150px, 0.9fr) 110px 120px`

/** Команда основного бота в реестре хранится как `self`. */
function botLabel(botName: string): string {
  return botName === 'self' ? 'mishgan_sol' : botName
}

/** Раздел «Команды»: реестр `bot_commands` одной таблицей-«островками». */
export function BotCommandsView() {
  const { isAdmin } = useAuth()
  const stateMutation = useUpdateBotCommandState()
  const { mutate: updateState, isPending, variables } = stateMutation
  const busyCommandId = isPending ? variables?.commandId : undefined
  const [offset, setOffset] = useOffset()
  const [search, setSearch] = useState('')
  const debouncedSearch = useDebouncedValue(search)
  const [addOpen, setAddOpen] = useState(false)

  const columns = useMemo<EntityColumn<BotCommandView>[]>(
    () => [
      {
        key: 'name',
        label: 'Команда',
        align: 'center',
        defaultDir: 'asc',
        sortValue: (command) => command.name.toLowerCase(),
        render: (command) => (
          <span className="min-w-0 truncate text-[var(--text)]">
            {command.name.startsWith('!') ? command.name : `!${command.name}`}
          </span>
        ),
      },
      {
        key: 'description',
        label: 'Описание',
        sortValue: (command) => command.description.toLowerCase(),
        render: (command) => (
          <span className="min-w-0 text-[var(--text)]">{command.description}</span>
        ),
      },
      {
        key: 'bot',
        label: 'Бот',
        align: 'center',
        sortValue: (command) => command.bot_name.toLowerCase(),
        render: (command) => (
          <span className="min-w-0 truncate text-[var(--text)]">
            {botLabel(command.bot_name)}
          </span>
        ),
      },
      {
        key: 'visible',
        label: 'Показывать',
        align: 'center',
        render: (command) => (
          <FlagToggle
            value={command.is_visible}
            label="Показывать в списке команд"
            onChange={
              isAdmin
                ? (next) =>
                    updateState({
                      commandId: command.id,
                      patch: { is_visible: next },
                    })
                : undefined
            }
            busy={busyCommandId === command.id}
          />
        ),
      },
      {
        key: 'access',
        label: 'Доступность',
        align: 'center',
        render: (command) => (
          <FlagToggle
            value={command.is_active}
            label="Команда доступна"
            onChange={
              isAdmin
                ? (next) =>
                    updateState({
                      commandId: command.id,
                      patch: { is_active: next },
                    })
                : undefined
            }
            busy={busyCommandId === command.id}
          />
        ),
      },
    ],
    [isAdmin, busyCommandId, updateState],
  )

  const { sortKey, sortDir, onSort } = useTableSort([], columns, {
    key: 'name',
    dir: 'asc',
  })

  // Поиск, сортировка и пагинация — на сервере.
  const query = useBotCommandsList({
    search: debouncedSearch.trim() || undefined,
    sort: sortKey,
    direction: sortDir,
    limit: PAGE_SIZE,
    offset,
  })

  useResetOffsetOn(setOffset, [debouncedSearch, sortKey, sortDir])

  const pageItems = query.data?.items ?? []
  const total = query.data?.total ?? 0
  const totalAll = query.data?.total_all ?? 0
  const aggregates = query.data?.aggregates

  return (
    <div className="flex flex-1 flex-col">
      <SectionHeader
        title="Команды"
        subtitle={
          query.isSuccess
            ? `Показано ${formatNumber(total)} из ${formatNumber(totalAll)}`
            : 'Реестр команд бота'
        }
        stats={
          query.isSuccess ? (
            <>
              <StatChip label="Всего" value={formatNumber(totalAll)} />
              <StatChip label="Ботов" value={formatNumber(aggregates?.bots ?? 0)} />
            </>
          ) : undefined
        }
        action={
          <button
            type="button"
            onClick={() => setAddOpen(true)}
            disabled={!isAdmin}
            title={isAdmin ? undefined : 'Добавлять команды могут только администраторы'}
            className="flex items-center gap-1.5 rounded-md bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-black transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            <Plus className="h-4 w-4" />
            Добавить команду
          </button>
        }
        hint={
          <>
            Команда бота:{' '}
            <span className="font-social text-[var(--accent)]">
              !команды [название команды]
            </span>{' '}
            — написать в чат Twitch для получения краткого описания команды
          </>
        }
      >
        <SearchInput
          value={search}
          onChange={setSearch}
          placeholder="Поиск по командам..."
          className="w-full sm:w-80"
        />
      </SectionHeader>

      {query.isLoading ? (
        <TableSkeleton columns={5} />
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : pageItems.length === 0 ? (
        <EmptyState hint="Измените поисковый запрос." />
      ) : (
        <div className="flex flex-1 flex-col p-6">
          <EntityList
            columns={columns}
            rows={pageItems}
            rowKey={(command) => command.id}
            sortKey={sortKey}
            sortDir={sortDir}
            onSort={onSort}
            gridTemplate={GRID}
            minWidth="900px"
          />
          <Pagination
            total={total}
            limit={PAGE_SIZE}
            offset={offset}
            onChange={setOffset}
          />
        </div>
      )}

      {addOpen ? <AddBotCommandModal open onClose={() => setAddOpen(false)} /> : null}
    </div>
  )
}
