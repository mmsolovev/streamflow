import { useCallback, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'

import type { ReleaseView } from '@/api/types'
import { CoverImage } from '@/components/entity/CoverImage'
import { EntityList } from '@/components/entity/EntityList'
import { RecommendersCell } from '@/components/entity/RecommendersCell'
import { TagsCell } from '@/components/entity/TagsCell'
import { TAGS_COLUMN_WIDTH, type EntityColumn } from '@/components/entity/types'
import { SectionHeader } from '@/components/layout/SectionHeader'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { FilterMenu } from '@/components/ui/FilterMenu'
import type { FilterOption } from '@/components/ui/FilterMenu'
import { FlagToggle } from '@/components/ui/FlagToggle'
import { Pagination } from '@/components/ui/Pagination'
import { SearchInput } from '@/components/ui/SearchInput'
import { TableSkeleton } from '@/components/ui/Skeleton'
import { StatChip } from '@/components/ui/StatChip'
import {
  useReleasesFilterOptions,
  useReleasesList,
  useSetReleaseInterested,
} from '@/features/releases/useReleases'
import { AddRecommendation } from '@/features/recommendations/AddRecommendation'
import { useDeleteRecommendation } from '@/features/recommendations/useRecommendations'
import { useAuth } from '@/features/auth/context'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { useFocusGameRow } from '@/hooks/useFocusGameRow'
import { useOffset, useResetOffsetOn } from '@/hooks/useOffset'
import { useTableSort } from '@/hooks/useTableSort'
import {
  formatDateNumeric,
  formatNumber,
  formatReleaseCountdown,
  formatTime,
  hasReleaseTime,
  isReleased,
  toSortTime,
} from '@/lib/format'
import { GAME_COVER_PLACEHOLDER } from '@/lib/games'
import { recKey } from '@/lib/recommenders'
import { buildTagFilterEntries, parseTagGroups } from '@/lib/tags'

const PAGE_SIZE = 24

const GRID = `minmax(190px, 0.9fr) minmax(300px, 2.2fr) minmax(190px, 3fr) 80px 96px minmax(160px, 1.6fr) ${TAGS_COLUMN_WIDTH}`

const tagKey = (value: string) => `tag:${value}`

interface ReleaseFlagActions {
  /** Есть ли право отмечать (только админ). */
  canEdit: boolean
  onToggleInterested: (release: ReleaseView, next: boolean) => void
  /** Id игры, для которой сейчас идёт сохранение. */
  busyGameId: number | null
}

function makeColumns(
  activeTags: string[],
  onTagClick: (value: string) => void,
  activeRecLogins: string[],
  onRecClick: (login: string) => void,
  actions: {
    canDeleteRecommender: ((login: string) => boolean) | undefined
    onDeleteRecommender: (item: ReleaseView, login: string) => void
    deletingLogin: string | null
  },
  flags: ReleaseFlagActions,
): EntityColumn<ReleaseView>[] {
  return [
    {
      key: 'release',
      label: 'Дата релиза',
      defaultDir: 'asc',
      align: 'center',
      sortValue: (release) => toSortTime(release.release_date) ?? Infinity,
      tieBreaks: [(a, b) => a.name.localeCompare(b.name, 'ru')],
      render: (release) => {
        const iso = release.release_date
        if (!iso) {
          return <span className="text-[var(--text-muted)]">—</span>
        }
        const released = isReleased(iso)
        const countdown = formatReleaseCountdown(iso)
        return (
          <span className="flex items-center justify-center gap-3">
            <span className="flex flex-col items-end leading-tight">
              <span>{formatDateNumeric(iso)}</span>
              {hasReleaseTime(iso) ? <span>{formatTime(iso)}</span> : null}
            </span>
            {released ? (
              <span className="leading-tight">доступна</span>
            ) : countdown ? (
              <span className="flex flex-col items-center leading-tight">
                <span>осталось</span>
                <span>{countdown}</span>
              </span>
            ) : null}
          </span>
        )
      },
    },
    {
      key: 'name',
      label: 'Игра',
      sortValue: (release) => release.name.toLowerCase(),
      defaultDir: 'asc',
      render: (release) => (
        <span className="flex min-w-0 items-center gap-2">
          <Link
            to={`/games/${release.id}`}
            title={release.name}
            className="shrink-0 transition-opacity hover:opacity-80"
          >
            <CoverImage
              src={release.cover_url}
              alt={release.name}
              fallback={GAME_COVER_PLACEHOLDER}
            />
          </Link>
          <Link
            to={`/games/${release.id}`}
            title={release.name}
            className="min-w-0 truncate font-medium transition-colors hover:text-[var(--accent)]"
          >
            {release.name}
          </Link>
        </span>
      ),
    },
    {
      key: 'description',
      label: 'Описание',
      render: (release) => {
        const text = release.description_ru || release.description_en || ''
        return (
          <span className="min-w-0 break-words text-sm leading-snug">{text || '—'}</span>
        )
      },
    },
    {
      key: 'steam',
      label: 'Ссылка',
      align: 'center',
      filterValue: (release) => Boolean(release.steam_url),
      render: (release) =>
        release.steam_url ? (
          <a
            href={release.steam_url}
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
      key: 'interested',
      label: 'Интересно',
      align: 'center',
      filterValue: (release) => release.interested,
      render: (release) => (
        <FlagToggle
          value={release.interested}
          label="Интересно"
          onChange={
            flags.canEdit ? (next) => flags.onToggleInterested(release, next) : undefined
          }
          busy={flags.busyGameId === release.id}
        />
      ),
    },
    {
      key: 'recommenders',
      label: 'Рекомендуют',
      sortValue: (release) => release.recommenders_count,
      defaultDir: 'desc',
      render: (release) => (
        <RecommendersCell
          gameId={release.id}
          entries={release.recommenders_list}
          count={release.recommenders_count}
          activeLogins={activeRecLogins}
          onLoginClick={onRecClick}
          canDelete={actions.canDeleteRecommender}
          onDelete={(login) => actions.onDeleteRecommender(release, login)}
          deletingLogin={actions.deletingLogin}
        />
      ),
    },
    {
      key: 'tags',
      label: 'Теги',
      className: 'text-sm',
      render: (release) => (
        <TagsCell
          groups={parseTagGroups(release.tags)}
          activeTags={activeTags}
          onTagClick={onTagClick}
        />
      ),
    },
  ]
}

export function ReleasesView() {
  const { user, canEdit } = useAuth()
  const deleteMutation = useDeleteRecommendation()
  const interestedMutation = useSetReleaseInterested()
  const [offset, setOffset] = useOffset()

  const [search, setSearch] = useState('')
  const debouncedSearch = useDebouncedValue(search)
  const [activeFilters, setActiveFilters] = useState<string[]>([])
  const [editMode, setEditMode] = useState(false)
  const [confirmTarget, setConfirmTarget] = useState<{
    item: ReleaseView
    login: string
    label: string
  } | null>(null)

  const toggleFilter = useCallback((key: string) => {
    setActiveFilters((prev) =>
      prev.includes(key) ? prev.filter((item) => item !== key) : [...prev, key],
    )
  }, [])

  const clearFilters = useCallback(() => setActiveFilters([]), [])

  // Сбрасывает поиск и фильтры — чтобы добавленная игра стала видна.
  const resetToAll = useCallback(() => {
    setSearch('')
    setActiveFilters([])
  }, [])

  const activeTags = useMemo(
    () =>
      activeFilters.filter((key) => key.startsWith('tag:')).map((key) => key.slice(4)),
    [activeFilters],
  )

  const activeRecLogins = useMemo(
    () =>
      activeFilters.filter((key) => key.startsWith('rec:')).map((key) => key.slice(4)),
    [activeFilters],
  )

  const columns = useMemo(
    () =>
      makeColumns(
        activeTags,
        (value) => toggleFilter(tagKey(value)),
        activeRecLogins,
        (login) => toggleFilter(recKey(login)),
        {
          canDeleteRecommender: editMode
            ? (login) => {
                if (!user) return false
                const own = user.login && login.toLowerCase() === user.login.toLowerCase()
                return Boolean(own) || canEdit
              }
            : undefined,
          onDeleteRecommender: (item, login) => {
            const entry = item.recommenders_list.find(
              (candidate) =>
                (candidate.user_login ?? '').toLowerCase() === login.toLowerCase(),
            )
            setConfirmTarget({
              item,
              login,
              label: entry?.display_name || entry?.user_login || login,
            })
          },
          deletingLogin: deleteMutation.isPending
            ? ((deleteMutation.variables as { login?: string } | undefined)?.login ??
              null)
            : null,
        },
        {
          canEdit,
          onToggleInterested: (release, interested) => {
            interestedMutation.mutate({ gameId: release.id, interested })
          },
          busyGameId: interestedMutation.isPending
            ? (interestedMutation.variables?.gameId ?? null)
            : null,
        },
      ),
    [
      activeTags,
      activeRecLogins,
      toggleFilter,
      user,
      deleteMutation,
      editMode,
      canEdit,
      interestedMutation,
    ],
  )

  const { sortKey, sortDir, onSort } = useTableSort([], columns, {
    key: 'release',
    dir: 'asc',
  })

  // Сортировка, поиск, фильтры и пагинация — на сервере.
  const query = useReleasesList({
    search: debouncedSearch.trim() || undefined,
    sort: sortKey,
    direction: sortDir,
    filters: activeFilters,
    limit: PAGE_SIZE,
    offset,
  })

  const options = useReleasesFilterOptions()

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
    const recommenderFilters = (options.data?.recommenders ?? []).map((entry) => ({
      key: recKey(entry.login),
      label: `Рекомендует: ${entry.label}`,
    }))
    return [...columnFilters, ...tagFilters, ...recommenderFilters]
  }, [columns, options.data])

  useResetOffsetOn(setOffset, [debouncedSearch, activeFilters, sortKey, sortDir])

  const { highlightId } = useFocusGameRow({
    rows: query.data?.items ?? [],
    allRows: query.data?.items ?? [],
    clearFilters: resetToAll,
    pageSize: PAGE_SIZE,
    offset,
    setOffset,
  })

  const pageItems = query.data?.items ?? []
  const total = query.data?.total ?? 0
  const totalAll = query.data?.total_all ?? 0
  const aggregates = query.data?.aggregates

  return (
    <div className="flex flex-1 flex-col">
      <SectionHeader
        title="Релизы"
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
                label="Интересные"
                value={formatNumber(aggregates?.interested ?? 0)}
              />
              <StatChip
                label="Доступны"
                value={formatNumber(aggregates?.released ?? 0)}
              />
            </>
          ) : undefined
        }
        hint={
          <>
            Команда бота:{' '}
            <span className="font-social text-[var(--accent)]">!рек [название игры]</span>{' '}
            — написать в чат Twitch для рекомендации стримеру игры
          </>
        }
        action={
          <>
            <AddRecommendation />
            {user ? (
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

      <ConfirmDialog
        open={confirmTarget !== null}
        title="Удалить рекомендацию"
        message={
          confirmTarget
            ? `Удалить рекомендацию «${confirmTarget.item.name}» от ${confirmTarget.label}?`
            : undefined
        }
        busy={deleteMutation.isPending}
        onCancel={() => setConfirmTarget(null)}
        onConfirm={() => {
          if (!confirmTarget) return
          const { item, login } = confirmTarget
          setConfirmTarget(null)
          deleteMutation.mutate(
            { gameId: item.id, login },
            {
              onSuccess: (result) =>
                toast.success(result.message || 'Рекомендация удалена.'),
              onError: (error) => toast.error(error.message),
            },
          )
        }}
      />

      {query.isLoading ? (
        <TableSkeleton columns={7} />
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : pageItems.length === 0 ? (
        <EmptyState hint="Измените фильтры или поисковый запрос." />
      ) : (
        <div className="flex flex-1 flex-col p-6">
          <EntityList
            columns={columns}
            rows={pageItems}
            rowKey={(release) => release.id}
            highlightedRowKey={highlightId}
            sortKey={sortKey}
            sortDir={sortDir}
            onSort={onSort}
            activeFilters={activeFilters}
            onFilterToggle={toggleFilter}
            gridTemplate={GRID}
            minWidth="1250px"
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
