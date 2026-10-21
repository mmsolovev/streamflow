import { useCallback, useMemo, useState } from 'react'

import type { StreamView } from '@/api/types'
import { DateCell } from '@/components/entity/DateCell'
import { EntityList } from '@/components/entity/EntityList'
import { GameCoverStrip } from '@/components/entity/GameCoverStrip'
import { TagsCell } from '@/components/entity/TagsCell'
import { TAGS_COLUMN_WIDTH, type EntityColumn } from '@/components/entity/types'
import { SectionHeader } from '@/components/layout/SectionHeader'
import { DatePickerMenu } from '@/components/ui/DatePickerMenu'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { FilterMenu } from '@/components/ui/FilterMenu'
import type { FilterOption } from '@/components/ui/FilterMenu'
import { Pagination } from '@/components/ui/Pagination'
import { SearchInput } from '@/components/ui/SearchInput'
import { TableSkeleton } from '@/components/ui/Skeleton'
import { StatChip } from '@/components/ui/StatChip'
import { useGamesCovers } from '@/features/games/useGames'
import { useStreamsFilterOptions, useStreamsList } from '@/features/streams/useStreams'
import { AddRecommendation } from '@/features/recommendations/AddRecommendation'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { useOffset, useResetOffsetOn } from '@/hooks/useOffset'
import { useTableSort } from '@/hooks/useTableSort'
import { formatHoursMinutes, formatNumber } from '@/lib/format'
import { normalizeGameName } from '@/lib/games'
import { buildTagFilterEntries, streamTagGroups } from '@/lib/tags'

const PAGE_SIZE = 24

const GRID = `120px minmax(200px, 2.5fr) minmax(350px, 2.2fr) 148px 80px 80px minmax(160px, 1.2fr) ${TAGS_COLUMN_WIDTH}`

const tagKey = (value: string) => `tag:${value}`

function makeColumns(
  activeTags: string[],
  onTagClick: (value: string) => void,
  gamesByName: Map<string, import('@/lib/games').GameRef>,
): EntityColumn<StreamView>[] {
  return [
    {
      key: 'date',
      label: 'Дата стрима',
      defaultDir: 'desc',
      align: 'center',
      sortValue: (stream) => stream.started_at,
      render: (stream) => <DateCell iso={stream.started_at} withTime />,
    },
    {
      key: 'title',
      label: 'Название',
      sortValue: (stream) => stream.title.toLowerCase(),
      defaultDir: 'asc',
      render: (stream) => (
        <span className="break-words leading-snug" title={stream.title}>
          {stream.title}
        </span>
      ),
    },
    {
      key: 'games',
      label: 'Игры',
      // Сортировка — по количеству игр на стриме.
      sortValue: (stream) => stream.games.length,
      defaultDir: 'desc',
      render: (stream) => (
        <GameCoverStrip names={stream.games} gamesByName={gamesByName} />
      ),
    },
    {
      key: 'duration',
      label: 'Длительность',
      align: 'center',
      sortValue: (stream) =>
        stream.duration_minutes ?? Math.round(stream.duration_hours * 60),
      render: (stream) =>
        formatHoursMinutes(
          stream.duration_minutes ?? Math.round(stream.duration_hours * 60),
        ),
    },
    {
      key: 'vod',
      label: 'Запись',
      align: 'center',
      filterValue: (stream) => Boolean(stream.vod_url),
      render: (stream) =>
        stream.vod_url ? (
          <a
            href={stream.vod_url}
            target="_blank"
            rel="noreferrer"
            className="font-social text-[#994cff] transition-opacity hover:opacity-80"
          >
            Twitch
          </a>
        ) : (
          <span className="text-[var(--text-muted)]">—</span>
        ),
    },
    {
      key: 'clips',
      label: 'Клипы',
      align: 'center',
      render: () => <span className="text-[var(--text-muted)]">—</span>,
    },
    {
      key: 'participants',
      label: 'Участники',
      sortValue: (stream) => stream.participants.join(', ').toLowerCase(),
      defaultDir: 'asc',
      render: (stream) => (
        <span className="truncate" title={stream.participants.join(', ')}>
          {stream.participants.join(', ') || '—'}
        </span>
      ),
    },
    {
      key: 'tags',
      label: 'Теги',
      className: 'text-sm',
      render: (stream) => (
        <TagsCell
          groups={streamTagGroups(stream.tags)}
          activeTags={activeTags}
          onTagClick={onTagClick}
        />
      ),
    },
  ]
}

export function StreamsView() {
  const gamesQuery = useGamesCovers()
  const [offset, setOffset] = useOffset()

  const [search, setSearch] = useState('')
  const debouncedSearch = useDebouncedValue(search)
  const [date, setDate] = useState('')
  const [activeFilters, setActiveFilters] = useState<string[]>([])

  const toggleFilter = useCallback((key: string) => {
    setActiveFilters((prev) =>
      prev.includes(key) ? prev.filter((item) => item !== key) : [...prev, key],
    )
  }, [])

  const clearFilters = useCallback(() => setActiveFilters([]), [])

  const activeTags = useMemo(
    () =>
      activeFilters.filter((key) => key.startsWith('tag:')).map((key) => key.slice(4)),
    [activeFilters],
  )

  const gamesByName = useMemo(() => {
    const map = new Map<string, import('@/lib/games').GameRef>()
    for (const game of gamesQuery.data ?? []) {
      map.set(normalizeGameName(game.name), {
        id: game.id,
        coverUrl: game.cover_url ?? null,
      })
    }
    return map
  }, [gamesQuery.data])

  const columns = useMemo(
    () => makeColumns(activeTags, (value) => toggleFilter(tagKey(value)), gamesByName),
    [activeTags, toggleFilter, gamesByName],
  )

  const { sortKey, sortDir, onSort } = useTableSort([], columns, {
    key: 'date',
    dir: 'desc',
  })

  // Сортировка, поиск, фильтры и пагинация — на сервере.
  const query = useStreamsList({
    search: debouncedSearch.trim() || undefined,
    sort: sortKey,
    direction: sortDir,
    filters: activeFilters,
    date: date || undefined,
    limit: PAGE_SIZE,
    offset,
  })

  const options = useStreamsFilterOptions()

  const filters = useMemo<FilterOption[]>(() => {
    const columnFilters = columns
      .filter((column) => column.filterValue)
      .map((column) => ({ key: column.key, label: column.label }))
    const tagFilters = buildTagFilterEntries(options.data?.tags ?? [], new Set()).map(
      (entry) => ({
        key: tagKey(entry.value),
        label: entry.label,
      }),
    )
    return [...columnFilters, ...tagFilters]
  }, [columns, options.data])

  const dateOptions = options.data?.dates ?? []

  const pageItems = query.data?.items ?? []
  const total = query.data?.total ?? 0
  const totalAll = query.data?.total_all ?? 0
  const aggregates = query.data?.aggregates

  useResetOffsetOn(setOffset, [debouncedSearch, date, activeFilters, sortKey, sortDir])

  return (
    <div className="flex flex-1 flex-col">
      <SectionHeader
        title="Стримы"
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
                label="С записью"
                value={formatNumber(aggregates?.with_vod ?? 0)}
              />
              <StatChip
                label="Всего часов"
                value={formatHoursMinutes(aggregates?.total_minutes ?? 0)}
              />
            </>
          ) : undefined
        }
        hint={
          <>
            Команда бота:{' '}
            <span className="font-social text-[var(--accent)]">
              !стримы [дата ДД.ММ.ГГ]
            </span>{' '}
            — написать в чат Twitch для получения краткой информации о стриме
          </>
        }
        action={<AddRecommendation />}
      >
        <SearchInput
          value={search}
          onChange={setSearch}
          placeholder="Поиск по названию/игре/дате..."
          className="w-full sm:w-80"
        />
        <DatePickerMenu value={date} dates={dateOptions} onChange={setDate} />
        <FilterMenu
          options={filters}
          active={activeFilters}
          onToggle={toggleFilter}
          onClear={clearFilters}
        />
      </SectionHeader>

      {query.isLoading ? (
        <TableSkeleton columns={8} />
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : pageItems.length === 0 ? (
        <EmptyState hint="Измените фильтры или поисковый запрос." />
      ) : (
        <div className="flex flex-1 flex-col p-6">
          <EntityList
            columns={columns}
            rows={pageItems}
            rowKey={(stream) => stream.id}
            sortKey={sortKey}
            sortDir={sortDir}
            onSort={onSort}
            activeFilters={activeFilters}
            onFilterToggle={toggleFilter}
            gridTemplate={GRID}
            rowClassName="min-h-20"
            minWidth="1400px"
          />
          <Pagination
            total={total}
            limit={PAGE_SIZE}
            offset={offset}
            onChange={setOffset}
          />
        </div>
      )}
    </div>
  )
}
