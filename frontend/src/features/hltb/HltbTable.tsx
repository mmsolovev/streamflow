import { useCallback, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Plus } from 'lucide-react'

import type { HltbView } from '@/api/types'
import { EntityList } from '@/components/entity/EntityList'
import { type EntityColumn } from '@/components/entity/types'
import { SectionHeader } from '@/components/layout/SectionHeader'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { Pagination } from '@/components/ui/Pagination'
import { SearchInput } from '@/components/ui/SearchInput'
import { TableSkeleton } from '@/components/ui/Skeleton'
import { StatChip } from '@/components/ui/StatChip'
import { useAuth } from '@/features/auth/context'
import { AddHltbModal } from '@/features/hltb/AddHltbModal'
import { useHltbList } from '@/features/hltb/useHltb'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { useOffset, useResetOffsetOn } from '@/hooks/useOffset'
import { useTableSort } from '@/hooks/useTableSort'
import { formatHltbTime, formatNumber } from '@/lib/format'

const PAGE_SIZE = 24

const GRID = `minmax(220px, 2.4fr) 104px 104px 116px 104px 96px 116px 150px`

const HLTB_URL = 'https://howlongtobeat.com/game/'

/** Раздел «HowLongToBeat»: время прохождения игр (по данным game_metadata_hltb). */
export function HltbTable() {
  const { isAdmin } = useAuth()
  const [offset, setOffset] = useOffset()
  const [addOpen, setAddOpen] = useState(false)

  const [search, setSearch] = useState('')
  const debouncedSearch = useDebouncedValue(search)

  const columns = useMemo<EntityColumn<HltbView>[]>(
    () => [
      {
        key: 'name',
        label: 'Игра',
        defaultDir: 'asc',
        sortValue: (item) => item.name.toLowerCase(),
        render: (item) => (
          <Link
            to={`/games/${item.id}`}
            title={item.name}
            className="min-w-0 truncate font-medium transition-colors hover:text-[var(--accent)]"
          >
            {item.name}
          </Link>
        ),
      },
      {
        key: 'all',
        label: 'Все стили',
        align: 'center',
        defaultDir: 'asc',
        sortValue: (item) => item.all_styles ?? Number.POSITIVE_INFINITY,
        render: (item) => formatHltbTime(item.all_styles),
      },
      {
        key: 'story',
        label: 'Сюжет',
        align: 'center',
        defaultDir: 'asc',
        sortValue: (item) => item.main_story ?? Number.POSITIVE_INFINITY,
        render: (item) => formatHltbTime(item.main_story),
      },
      {
        key: 'extra',
        label: 'Сюжет+Доп',
        align: 'center',
        defaultDir: 'asc',
        sortValue: (item) => item.main_extra ?? Number.POSITIVE_INFINITY,
        render: (item) => formatHltbTime(item.main_extra),
      },
      {
        key: 'completionist',
        label: 'Полное',
        align: 'center',
        defaultDir: 'asc',
        sortValue: (item) => item.completionist ?? Number.POSITIVE_INFINITY,
        render: (item) => formatHltbTime(item.completionist),
      },
      {
        key: 'coop',
        label: 'Кооп',
        align: 'center',
        defaultDir: 'asc',
        sortValue: (item) => item.coop ?? Number.POSITIVE_INFINITY,
        render: (item) => formatHltbTime(item.coop),
      },
      {
        key: 'multiplayer',
        label: 'Мультиплеер',
        align: 'center',
        defaultDir: 'asc',
        sortValue: (item) => item.multiplayer ?? Number.POSITIVE_INFINITY,
        render: (item) => formatHltbTime(item.multiplayer),
      },
      {
        key: 'link',
        label: 'Ссылка',
        align: 'center',
        render: (item) =>
          item.hltb_id ? (
            <a
              href={`${HLTB_URL}${item.hltb_id}`}
              target="_blank"
              rel="noreferrer"
              className="font-social text-[var(--accent)] transition-opacity hover:opacity-80"
            >
              HowLongToBeat
            </a>
          ) : (
            <span className="text-[var(--text-muted)]">—</span>
          ),
      },
    ],
    [],
  )

  const { sortKey, sortDir, onSort } = useTableSort([], columns, {
    key: 'all',
    dir: 'asc',
  })

  // Сортировка, поиск и пагинация — на сервере.
  const query = useHltbList({
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

  const handleSearch = useCallback((value: string) => setSearch(value), [])

  return (
    <div className="flex flex-1 flex-col">
      <SectionHeader
        title="HowLongToBeat"
        noUppercase
        plainTitle
        subtitle={
          query.isSuccess
            ? `Показано ${formatNumber(total)} из ${formatNumber(totalAll)}`
            : 'Раздел статистики'
        }
        stats={
          query.isSuccess ? (
            <>
              <StatChip label="Всего" value={formatNumber(totalAll)} />
              <StatChip
                label="С временем"
                value={formatNumber(aggregates?.with_time ?? 0)}
              />
            </>
          ) : undefined
        }
        action={
          isAdmin ? (
            <button
              type="button"
              onClick={() => setAddOpen(true)}
              className="flex items-center gap-1.5 rounded-md bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-black transition-opacity hover:opacity-90"
            >
              <Plus className="h-4 w-4" />
              Добавить игру
            </button>
          ) : undefined
        }
        hint={
          <>
            Команда бота:{' '}
            <span className="text-[var(--accent)]">!hltb [название игры]</span> — время
            прохождения с сайта HowLongToBeat
          </>
        }
      >
        <SearchInput
          value={search}
          onChange={handleSearch}
          placeholder="Поиск игры..."
          className="w-full sm:w-80"
        />
      </SectionHeader>

      {query.isLoading ? (
        <TableSkeleton columns={8} />
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : pageItems.length === 0 ? (
        <EmptyState hint="Измените поисковый запрос." />
      ) : (
        <div className="flex flex-1 flex-col p-6">
          <EntityList
            columns={columns}
            rows={pageItems}
            rowKey={(item) => item.id}
            sortKey={sortKey}
            sortDir={sortDir}
            onSort={onSort}
            gridTemplate={GRID}
          />
          <Pagination
            total={total}
            limit={PAGE_SIZE}
            offset={offset}
            onChange={setOffset}
          />
        </div>
      )}

      {addOpen ? <AddHltbModal open onClose={() => setAddOpen(false)} /> : null}
    </div>
  )
}
