import { useCallback, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Check, Copy } from 'lucide-react'

import type { GameView } from '@/api/types'
import { CoverImage } from '@/components/entity/CoverImage'
import { DateCell } from '@/components/entity/DateCell'
import { EntityList } from '@/components/entity/EntityList'
import { TagsCell } from '@/components/entity/TagsCell'
import { TAGS_COLUMN_WIDTH, type EntityColumn } from '@/components/entity/types'
import { SectionHeader } from '@/components/layout/SectionHeader'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { FilterMenu } from '@/components/ui/FilterMenu'
import type { FilterOption } from '@/components/ui/FilterMenu'
import { FlagToggle } from '@/components/ui/FlagToggle'
import { Pagination } from '@/components/ui/Pagination'
import { SearchInput } from '@/components/ui/SearchInput'
import { TableSkeleton } from '@/components/ui/Skeleton'
import { StatChip } from '@/components/ui/StatChip'
import { useAuth } from '@/features/auth/context'
import {
  useGamesFilterOptions,
  useGamesList,
  useUpdateGameState,
} from '@/features/games/useGames'
import { AddRecommendation } from '@/features/recommendations/AddRecommendation'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { useOffset, useResetOffsetOn } from '@/hooks/useOffset'
import { useTableSort } from '@/hooks/useTableSort'
import { formatHoursMinutes, formatNumber, toSortTime } from '@/lib/format'
import { GAME_COVER_PLACEHOLDER } from '@/lib/games'
import { buildTagFilterEntries, parseTagGroups } from '@/lib/tags'

const PAGE_SIZE = 24

const GRID = `150px minmax(280px, 2.5fr) 72px 112px 96px 140px 76px 126px 96px 76px 76px ${TAGS_COLUMN_WIDTH}`

const tagKey = (value: string) => `tag:${value}`

interface GameFlagActions {
  /** Есть ли право отмечать (только админ). */
  canEdit: boolean
  onToggleLiked: (game: GameView, next: boolean) => void
  onToggleCompleted: (game: GameView, next: boolean) => void
  /** Id игры, для которой сейчас идёт сохранение. */
  busyGameId: number | null
}

/** Копирует название игры в буфер обмена. */
function CopyNameButton({ name }: { name: string }) {
  const [copied, setCopied] = useState(false)

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(name)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      // Буфер обмена недоступен — молча игнорируем.
    }
  }

  return (
    <button
      type="button"
      onClick={() => void handleCopy()}
      title="Скопировать название"
      aria-label="Скопировать название"
      className="shrink-0 rounded p-1 text-[var(--text-muted)] transition-colors hover:text-[var(--accent)]"
    >
      {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
    </button>
  )
}

function makeColumns(
  activeTags: string[],
  onTagClick: (value: string) => void,
  flags: GameFlagActions,
): EntityColumn<GameView>[] {
  return [
    {
      key: 'last',
      label: 'Последний стрим',
      defaultDir: 'desc',
      align: 'center',
      sortValue: (game) => toSortTime(game.last_stream) ?? -Infinity,
      tieBreaks: [(a, b) => a.name.localeCompare(b.name, 'ru')],
      render: (game) =>
        game.last_stream ? (
          <Link
            to={`/streams?date=${game.last_stream.slice(0, 10)}${
              game.last_stream_id ? `&focus=${game.last_stream_id}` : ''
            }`}
            title="Перейти к стриму"
            className="transition-colors hover:text-[var(--accent)]"
          >
            <DateCell iso={game.last_stream} />
          </Link>
        ) : (
          <span className="text-[var(--text-muted)]">—</span>
        ),
    },
    {
      key: 'name',
      label: 'Название игры',
      sortValue: (game) => game.name.toLowerCase(),
      defaultDir: 'asc',
      render: (game) => (
        <span className="flex min-w-0 items-center gap-2">
          <Link
            to={`/games/${game.id}`}
            title={game.name}
            className="shrink-0 transition-opacity hover:opacity-80"
          >
            <CoverImage
              src={game.cover_url}
              alt={game.name}
              fallback={GAME_COVER_PLACEHOLDER}
            />
          </Link>
          <Link
            to={`/games/${game.id}`}
            title={game.name}
            className="min-w-0 flex-1 truncate font-medium transition-colors hover:text-[var(--accent)]"
          >
            {game.name}
          </Link>
          <CopyNameButton name={game.name} />
        </span>
      ),
    },
    {
      key: 'rank',
      label: 'Ранг',
      align: 'center',
      sortValue: (game) => game.rank,
      render: (game) => (
        <Link
          to={`/games/${game.id}`}
          className="transition-colors hover:text-[var(--accent)]"
        >
          #{game.rank}
        </Link>
      ),
    },
    {
      key: 'hours',
      label: 'Часов',
      align: 'center',
      sortValue: (game) => game.hours,
      render: (game) => (
        <Link
          to={`/games/${game.id}`}
          className="transition-colors hover:text-[var(--accent)]"
        >
          {formatHoursMinutes(game.duration_minutes)}
        </Link>
      ),
    },
    {
      key: 'streams',
      label: 'Стримов',
      align: 'center',
      sortValue: (game) => game.streams_count,
      render: (game) => (
        <Link
          to={`/games/${game.id}`}
          className="transition-colors hover:text-[var(--accent)]"
        >
          {formatNumber(game.streams_count)}
        </Link>
      ),
    },
    {
      key: 'hltb',
      label: 'HowLongToBeat',
      align: 'center',
      noUppercase: true,
      sortValue: (game) => game.hltb_all_styles ?? -1,
      render: (game) =>
        game.hltb_all_styles === null ? (
          '—'
        ) : (
          <Link
            to={`/hltb?search=${encodeURIComponent(game.name)}&focus=${game.id}`}
            title="Показать в HowLongToBeat"
            className="transition-colors hover:text-[var(--accent)]"
          >
            {formatHoursMinutes(Math.round(game.hltb_all_styles * 60))}
          </Link>
        ),
    },
    {
      key: 'steam',
      label: 'Ссылка',
      align: 'center',
      filterValue: (game) => Boolean(game.steam_url),
      render: (game) =>
        game.steam_url ? (
          <a
            href={game.steam_url}
            target="_blank"
            rel="noreferrer"
            className="font-social text-[#66c0f4] transition-opacity hover:opacity-80"
          >
            Steam
          </a>
        ) : (
          <span className="text-[var(--text-muted)]">—</span>
        ),
    },
    {
      key: 'liked',
      label: 'Понравилось',
      align: 'center',
      filterValue: (game) => game.liked,
      render: (game) => (
        <FlagToggle
          value={game.liked}
          label="Понравилось"
          onChange={flags.canEdit ? (next) => flags.onToggleLiked(game, next) : undefined}
          busy={flags.busyGameId === game.id}
        />
      ),
    },
    {
      key: 'completed',
      label: 'Пройдено',
      align: 'center',
      filterValue: (game) => game.completed,
      render: (game) => (
        <FlagToggle
          value={game.completed}
          label="Пройдено"
          onChange={
            flags.canEdit ? (next) => flags.onToggleCompleted(game, next) : undefined
          }
          busy={flags.busyGameId === game.id}
        />
      ),
    },
    {
      key: 'clips',
      label: 'Клипы',
      align: 'center',
      render: () => <span className="text-[var(--text-muted)]">—</span>,
    },
    {
      key: 'review',
      label: 'Отзыв',
      align: 'center',
      // Заглушка «на будущее» — фильтра по отзывам пока нет.
      render: () => <span className="text-[var(--text-muted)]">—</span>,
    },
    {
      key: 'tags',
      label: 'Теги',
      className: 'text-sm',
      render: (game) => (
        <TagsCell
          groups={parseTagGroups(game.tags)}
          activeTags={activeTags}
          onTagClick={onTagClick}
        />
      ),
    },
  ]
}

export function GamesView() {
  const { canEdit } = useAuth()
  const stateMutation = useUpdateGameState()
  const [offset, setOffset] = useOffset()

  const [search, setSearch] = useState('')
  const debouncedSearch = useDebouncedValue(search)
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

  const toggleLiked = useCallback(
    (game: GameView, liked: boolean) => {
      stateMutation.mutate({
        gameId: game.id,
        liked,
        completed: game.completed,
      })
    },
    [stateMutation],
  )

  const toggleCompleted = useCallback(
    (game: GameView, completed: boolean) => {
      stateMutation.mutate({
        gameId: game.id,
        liked: game.liked,
        completed,
      })
    },
    [stateMutation],
  )

  const columns = useMemo(
    () =>
      makeColumns(activeTags, (value) => toggleFilter(tagKey(value)), {
        canEdit,
        onToggleLiked: toggleLiked,
        onToggleCompleted: toggleCompleted,
        busyGameId: stateMutation.isPending
          ? (stateMutation.variables?.gameId ?? null)
          : null,
      }),
    [
      activeTags,
      toggleFilter,
      canEdit,
      toggleLiked,
      toggleCompleted,
      stateMutation.isPending,
      stateMutation.variables,
    ],
  )

  const { sortKey, sortDir, onSort } = useTableSort([], columns, {
    key: 'last',
    dir: 'desc',
  })

  // Сортировка, поиск, фильтры и пагинация — на сервере.
  const query = useGamesList({
    search: debouncedSearch.trim() || undefined,
    sort: sortKey,
    direction: sortDir,
    filters: activeFilters,
    limit: PAGE_SIZE,
    offset,
  })

  const options = useGamesFilterOptions()

  const filters = useMemo<FilterOption[]>(() => {
    const columnFilters = columns
      .filter((column) => column.filterValue)
      .map((column) => ({ key: column.key, label: column.label }))
    const tagFilters = buildTagFilterEntries(
      options.data?.tags ?? [],
      new Set(options.data?.platforms ?? []),
    ).map((entry) => ({
      key: tagKey(entry.value),
      label: entry.label,
    }))
    return [...columnFilters, ...tagFilters]
  }, [columns, options.data])

  const pageItems = query.data?.items ?? []
  const total = query.data?.total ?? 0
  const totalAll = query.data?.total_all ?? 0
  const aggregates = query.data?.aggregates

  useResetOffsetOn(setOffset, [debouncedSearch, activeFilters, sortKey, sortDir])

  return (
    <div className="flex flex-1 flex-col">
      <SectionHeader
        title="Игры"
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
                label="Пройдено"
                value={formatNumber(aggregates?.completed ?? 0)}
              />
              <StatChip label="Любимые" value={formatNumber(aggregates?.liked ?? 0)} />
            </>
          ) : undefined
        }
        hint={
          <>
            Команда бота:{' '}
            <span className="font-social text-[var(--accent)]">
              !игры [название игры]
            </span>{' '}
            — написать в чат Twitch для получения краткой информации об игре
          </>
        }
        action={<AddRecommendation />}
      >
        <SearchInput
          value={search}
          onChange={setSearch}
          placeholder="Поиск игры..."
          className="w-full sm:w-80"
        />
        <FilterMenu
          options={filters}
          active={activeFilters}
          onToggle={toggleFilter}
          onClear={clearFilters}
        />
      </SectionHeader>

      {query.isLoading ? (
        <TableSkeleton columns={12} />
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : pageItems.length === 0 ? (
        <EmptyState hint="Измените фильтры или поисковый запрос." />
      ) : (
        <div className="flex flex-1 flex-col p-6">
          <EntityList
            columns={columns}
            rows={pageItems}
            rowKey={(game) => game.id}
            sortKey={sortKey}
            sortDir={sortDir}
            onSort={onSort}
            activeFilters={activeFilters}
            onFilterToggle={toggleFilter}
            gridTemplate={GRID}
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
