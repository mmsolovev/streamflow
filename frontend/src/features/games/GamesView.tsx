import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Check, Copy } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'

import type { GameView } from '@/api/types'
import type { CurrentStreamGame, GameReviewLink } from '@/api/types'
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
import { GameReviewCell } from '@/features/games/GameReviewCell'
import {
  useCurrentStreamGames,
  useGamesFilterOptions,
  useGamesList,
  useUpdateGameReviews,
  useUpdateGameState,
} from '@/features/games/useGames'
import { AddRecommendation } from '@/features/recommendations/AddRecommendation'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { useOffset, useResetOffsetOn } from '@/hooks/useOffset'
import { useTableSort } from '@/hooks/useTableSort'
import {
  formatDateNumeric,
  formatHoursMinutes,
  formatNumber,
  formatTime,
  toSortTime,
} from '@/lib/format'
import { GAME_COVER_PLACEHOLDER } from '@/lib/games'
import { buildTagFilterEntries, parseTagGroups } from '@/lib/tags'

const PAGE_SIZE = 24

const GRID = `150px minmax(280px, 2.5fr) 72px 112px 96px 140px 76px 126px 96px 76px 76px ${TAGS_COLUMN_WIDTH}`

const tagKey = (value: string) => `tag:${value}`

type GameTableRow = GameView & {
  current?: CurrentStreamGame
  currentStandalone?: boolean
}

function currentGameRow(current: CurrentStreamGame): GameTableRow {
  if (current.game) {
    return { ...current.game, current }
  }
  return {
    id: current.game_id ?? 0,
    name: current.name,
    rank: 0,
    streams_count: 0,
    hours: 0,
    duration_minutes: null,
    last_stream: current.started_at,
    last_stream_id: null,
    hltb_all_styles: null,
    steam_url: current.steam_url ?? null,
    cover_url: current.cover_url ?? null,
    liked: false,
    completed: false,
    tags: '',
    review_links: [],
    current,
    currentStandalone: true,
  }
}

interface GameFlagActions {
  /** Есть ли право отмечать (только админ). */
  canEdit: boolean
  onToggleLiked: (game: GameView, next: boolean) => void
  onToggleCompleted: (game: GameView, next: boolean) => void
  /** Id игры, для которой сейчас идёт сохранение. */
  busyGameId: number | null
}

interface GameReviewActions {
  editMode: boolean
  busyGameId: number | null
  onSave: (game: GameView, links: GameReviewLink[]) => Promise<void>
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
  reviews: GameReviewActions,
): EntityColumn<GameTableRow>[] {
  return [
    {
      key: 'last',
      label: 'Последний стрим',
      defaultDir: 'desc',
      align: 'center',
      sortValue: (game) =>
        toSortTime(game.current?.first_played_at ?? game.last_stream) ?? -Infinity,
      tieBreaks: [(a, b) => a.name.localeCompare(b.name, 'ru')],
      render: (game) =>
        game.current ? (
          <span className="flex flex-col items-center leading-tight">
            {!game.currentStandalone && game.last_stream ? (
              <Link
                to={`/streams?date=${game.last_stream.slice(0, 10)}${
                  game.last_stream_id ? `&focus=${game.last_stream_id}` : ''
                }`}
                title="Перейти к последнему завершённому стриму"
                className="transition-colors hover:text-[var(--accent)]"
              >
                <DateCell iso={game.last_stream} />
              </Link>
            ) : null}
            <span className="text-xs text-[var(--accent)]">
              +{formatDateNumeric(game.current.first_played_at)}{' '}
              {formatTime(game.current.first_played_at)}
            </span>
          </span>
        ) : game.last_stream ? (
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
          null
        ),
    },
    {
      key: 'name',
      label: 'Название игры',
      sortValue: (game) => game.name.toLowerCase(),
      defaultDir: 'asc',
      render: (game) => {
        const gameId = game.current ? game.current.game_id : game.id
        const cover = (
          <CoverImage
            src={game.cover_url}
            alt={game.name}
            fallback={GAME_COVER_PLACEHOLDER}
          />
        )
        return (
          <span className="flex min-w-0 items-center gap-2">
            {gameId != null ? (
              <Link
                to={`/games/${gameId}`}
                title={game.name}
                className="shrink-0 transition-opacity hover:opacity-80"
              >
                {cover}
              </Link>
            ) : (
              <span className="shrink-0">{cover}</span>
            )}
            {gameId != null ? (
              <Link
                to={`/games/${gameId}`}
                title={game.name}
                className="min-w-0 flex-1 whitespace-normal break-words font-medium transition-colors hover:text-[var(--accent)]"
              >
                {game.name}
              </Link>
            ) : (
              <span className="min-w-0 flex-1 whitespace-normal break-words font-medium">
                {game.name}
              </span>
            )}
            {game.currentStandalone ? null : <CopyNameButton name={game.name} />}
          </span>
        )
      },
    },
    {
      key: 'rank',
      label: 'Ранг',
      align: 'center',
      sortValue: (game) => game.rank,
      render: (game) => game.currentStandalone ? null : (
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
      sortValue: (game) =>
        game.current
          ? (game.currentStandalone ? 0 : game.duration_minutes ?? 0) +
            game.current.duration_minutes
          : game.duration_minutes ?? -1,
      render: (game) =>
        game.current ? (
          <span className="flex flex-col items-center leading-tight">
            {!game.currentStandalone &&
            game.duration_minutes != null &&
            game.duration_minutes > 0 ? (
              <Link
                to={`/games/${game.id}`}
                className="transition-colors hover:text-[var(--accent)]"
              >
                {formatHoursMinutes(game.duration_minutes)}
              </Link>
            ) : null}
            {game.current.duration_minutes > 0 ? (
              <span className="text-[var(--accent)]">
                +{formatHoursMinutes(game.current.duration_minutes)}
              </span>
            ) : null}
          </span>
        ) : (
          <Link
            to={`/games/${game.id}`}
            className="transition-colors hover:text-[var(--accent)]"
          >
            {game.duration_minutes == null || game.duration_minutes <= 0
              ? null
              : formatHoursMinutes(game.duration_minutes)}
          </Link>
        ),
    },
    {
      key: 'streams',
      label: 'Стримов',
      align: 'center',
      sortValue: (game) => game.streams_count,
      render: (game) =>
        game.current ? (
          <span className="flex flex-col items-center leading-tight">
            {!game.currentStandalone ? (
              <Link
                to={`/games/${game.id}`}
                className="transition-colors hover:text-[var(--accent)]"
              >
                {formatNumber(game.streams_count)}
              </Link>
            ) : null}
            <span className="text-[var(--accent)]">+1</span>
          </span>
        ) : (
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
        game.currentStandalone ||
        game.hltb_all_styles == null ||
        game.hltb_all_styles <= 0 ? (
          null
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
      filterValue: (game) =>
        Boolean(game.currentStandalone ? game.current?.steam_url : game.steam_url),
      render: (game) =>
        (game.currentStandalone ? game.current?.steam_url : game.steam_url) ? (
          <a
            href={
              (game.currentStandalone ? game.current?.steam_url : game.steam_url) ??
              undefined
            }
            target="_blank"
            rel="noreferrer"
            className="font-social text-[#66c0f4] transition-opacity hover:opacity-80"
          >
            Steam
          </a>
        ) : null,
    },
    {
      key: 'liked',
      label: 'Понравилось',
      align: 'center',
      filterValue: (game) => !game.currentStandalone && game.liked,
      render: (game) => game.currentStandalone ? null : (
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
      filterValue: (game) => !game.currentStandalone && game.completed,
      render: (game) => game.currentStandalone ? null : (
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
      render: (game) =>
        game.currentStandalone ? null : (
          <Link
            to={`/media/clips?period=all&filters=game%3A${game.id}`}
            className="font-social text-[var(--accent)] transition-opacity hover:opacity-80"
          >
            Клипы
          </Link>
        ),
    },
    {
      key: 'review',
      label: 'Отзыв',
      align: 'center',
      filterValue: (game) =>
        !game.currentStandalone && (game.review_links?.length ?? 0) > 0,
      render: (game) => game.currentStandalone ? null : (
        <GameReviewCell
          links={game.review_links ?? []}
          editMode={reviews.editMode}
          busy={reviews.busyGameId === game.id}
          onSave={(links) => reviews.onSave(game, links)}
        />
      ),
    },
    {
      key: 'tags',
      label: 'Теги',
      className: 'text-sm',
      render: (game) => game.currentStandalone ? null : (
        <TagsCell
          groups={parseTagGroups(game.tags)}
          activeTags={activeTags}
          onTagClick={onTagClick}
        />
      ),
    },
  ]
}

function currentAwareSortValue(
  game: GameTableRow,
  sortKey: string,
  column: EntityColumn<GameTableRow>,
): string | number | null {
  if (!game.current) {
    if (sortKey === 'last') return toSortTime(game.last_stream)
    if (sortKey === 'hours') return game.duration_minutes
    return column.sortValue?.(game) ?? null
  }

  switch (sortKey) {
    case 'last':
      return toSortTime(game.current.first_played_at)
    case 'name':
      return game.name.toLowerCase()
    case 'rank':
      return game.currentStandalone ? null : game.rank
    case 'hours':
      return (
        (game.currentStandalone ? 0 : game.duration_minutes ?? 0) +
        game.current.duration_minutes
      )
    case 'streams':
      return game.currentStandalone ? null : game.streams_count
    case 'hltb':
      return game.currentStandalone ? null : game.hltb_all_styles
    default:
      return column.sortValue?.(game) ?? null
  }
}

function compareGameRows(
  a: GameTableRow,
  b: GameTableRow,
  column: EntityColumn<GameTableRow>,
  direction: 'asc' | 'desc',
): number {
  const aValue = currentAwareSortValue(a, column.key, column)
  const bValue = currentAwareSortValue(b, column.key, column)
  if (aValue == null || bValue == null) {
    if (aValue == null && bValue != null) return 1
    if (aValue != null && bValue == null) return -1
  } else {
    const comparison =
      typeof aValue === 'string' && typeof bValue === 'string'
        ? aValue.localeCompare(bValue, 'ru')
        : Number(aValue) - Number(bValue)
    if (comparison !== 0) return direction === 'asc' ? comparison : -comparison
  }

  for (const tieBreak of column.tieBreaks ?? []) {
    const comparison = tieBreak(a, b)
    if (comparison !== 0) return comparison
  }
  return a.name.localeCompare(b.name, 'ru')
}

export function GamesView() {
  const { canEdit } = useAuth()
  const queryClient = useQueryClient()
  const stateMutation = useUpdateGameState()
  const reviewsMutation = useUpdateGameReviews()
  const currentGamesQuery = useCurrentStreamGames()
  const previousCurrentGameKeys = useRef<string | undefined>(undefined)
  const saveReviews = reviewsMutation.mutateAsync
  const [offset, setOffset] = useOffset()

  const [search, setSearch] = useState('')
  const debouncedSearch = useDebouncedValue(search)
  const [activeFilters, setActiveFilters] = useState<string[]>([])
  const [editMode, setEditMode] = useState(false)

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
      makeColumns(
        activeTags,
        (value) => toggleFilter(tagKey(value)),
        {
          canEdit,
          onToggleLiked: toggleLiked,
          onToggleCompleted: toggleCompleted,
          busyGameId: stateMutation.isPending
            ? (stateMutation.variables?.gameId ?? null)
            : null,
        },
        {
          editMode,
          busyGameId: reviewsMutation.isPending
            ? (reviewsMutation.variables?.gameId ?? null)
            : null,
          onSave: async (game, links) => {
            await saveReviews({ gameId: game.id, links })
          },
        },
      ),
    [
      activeTags,
      toggleFilter,
      canEdit,
      editMode,
      reviewsMutation.isPending,
      reviewsMutation.variables,
      saveReviews,
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

  const pageItems = useMemo(() => query.data?.items ?? [], [query.data?.items])
  const { currentRows, displayRows } = useMemo(() => {
    const liveGames = currentGamesQuery.data ?? []
    const currentByGameId = new Map<number, CurrentStreamGame>()
    for (const game of liveGames) {
      if (game.game_id != null) currentByGameId.set(game.game_id, game)
    }

    const visibleGameIds = new Set(pageItems.map((game) => game.id))
    const mergedRows: GameTableRow[] = pageItems.flatMap((game) => {
      const current = currentByGameId.get(game.id)
      return current ? [{ ...game, current }] : []
    })
    const standaloneRows: GameTableRow[] = liveGames
      .filter((game) => game.game_id == null || !visibleGameIds.has(game.game_id))
      .map(currentGameRow)
    const currentRows: GameTableRow[] = [...mergedRows, ...standaloneRows]
    const mergedGameIds = new Set(mergedRows.map((game) => game.id))
    const historicalRows: GameTableRow[] = pageItems.filter(
      (game) => !mergedGameIds.has(game.id),
    )
    const sortColumn = columns.find((column) => column.key === sortKey) ?? columns[0]
    const displayRows: GameTableRow[] = [...currentRows, ...historicalRows].sort(
      (a, b) => compareGameRows(a, b, sortColumn, sortDir),
    )
    return {
      currentRows,
      displayRows,
    }
  }, [columns, currentGamesQuery.data, pageItems, sortDir, sortKey])
  useEffect(() => {
    if (!currentGamesQuery.isFetched) return
    const keys = (currentGamesQuery.data ?? []).map((game) => game.key).join('|')
    const previousKeys = previousCurrentGameKeys.current
    previousCurrentGameKeys.current = keys
    if (previousKeys === undefined || previousKeys !== keys) {
      void queryClient.invalidateQueries({ queryKey: ['games', 'list'] })
    }
  }, [currentGamesQuery.data, currentGamesQuery.isFetched, queryClient])
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
            ? `Показано ${formatNumber(total)} из ${formatNumber(totalAll)}${
                currentRows.length > 0 ? ' + игры стрима' : ''
              }`
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
        action={
          <>
            <AddRecommendation />
            {canEdit ? (
              <button
                type="button"
                onClick={() => setEditMode((value) => !value)}
                className={
                  editMode
                    ? 'rounded-md bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-black transition-opacity hover:opacity-90'
                    : 'rounded-md border border-white/15 px-3 py-1.5 text-sm text-[var(--text-muted)] transition-colors hover:bg-white/5 hover:text-[var(--text)]'
                }
              >
                Редактировать
              </button>
            ) : null}
          </>
        }
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

      {query.isLoading && currentRows.length === 0 ? (
        <TableSkeleton columns={12} />
      ) : query.isError && currentRows.length === 0 ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : displayRows.length === 0 ? (
        <EmptyState hint="Измените фильтры или поисковый запрос." />
      ) : (
        <div className="flex flex-1 flex-col p-6">
          <EntityList
            columns={columns}
            rows={displayRows}
            rowKey={(game) => game.current?.key ?? game.id}
            sortKey={sortKey}
            sortDir={sortDir}
            onSort={onSort}
            activeFilters={activeFilters}
            onFilterToggle={toggleFilter}
            rowClassName={(game) => (game.current ? 'hot-island' : '')}
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
