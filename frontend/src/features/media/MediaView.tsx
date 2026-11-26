import { useCallback, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { ArrowDownWideNarrow, CalendarDays, Eye, Pencil } from 'lucide-react'

import { Pagination } from '@/components/ui/Pagination'
import { SearchInput } from '@/components/ui/SearchInput'
import { SectionHeader } from '@/components/layout/SectionHeader'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { FilterMenu } from '@/components/ui/FilterMenu'
import type { FilterOption } from '@/components/ui/FilterMenu'
import { Skeleton } from '@/components/ui/Skeleton'
import type { MediaSection } from '@/config/nav'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { useOffset, useResetOffsetOn } from '@/hooks/useOffset'
import { formatNumber } from '@/lib/format'
import { useAuth } from '@/features/auth/context'
import type { RecordingView } from '@/api/types'
import {
  listClips,
  listMediaFilterOptions,
  listRecordings,
  type ClipPeriod,
  type MediaSort,
} from './api'
import { MediaCard, type MediaItem } from './MediaCard'
import { MediaPlayerModal } from './MediaPlayerModal'
import { RecordingPreviewEditModal } from './RecordingPreviewEditModal'

const PAGE_SIZE = 24
const CLIP_PERIODS: { key: ClipPeriod; label: string }[] = [
  { key: 'day', label: 'День' },
  { key: 'week', label: 'Неделя' },
  { key: 'month', label: 'Месяц' },
  { key: 'all', label: 'Всё время' },
]

export function MediaView({ section }: { section: MediaSection }) {
  const isClips = section === 'clips'
  const { canEdit } = useAuth()
  const [offset, setOffset] = useOffset()
  const [searchParams, setSearchParams] = useSearchParams()
  const [search, setSearch] = useState('')
  const [period, setPeriod] = useState<ClipPeriod>(() => {
    const initial = searchParams.get('period')
    return CLIP_PERIODS.some((item) => item.key === initial)
      ? (initial as ClipPeriod)
      : 'week'
  })
  const [activeFilters, setActiveFilters] = useState(() =>
    searchParams.getAll('filters'),
  )
  const [sort, setSort] = useState<MediaSort>(isClips ? 'views' : 'date')
  const [selectedItem, setSelectedItem] = useState<MediaItem | null>(null)
  const [editingRecording, setEditingRecording] = useState<RecordingView | null>(null)
  const [editMode, setEditMode] = useState(false)
  const debouncedSearch = useDebouncedValue(search, 250)

  const toggleFilter = useCallback(
    (key: string) => {
      const next = activeFilters.includes(key)
        ? activeFilters.filter((item) => item !== key)
        : [...activeFilters, key]
      setActiveFilters(next)
      setSearchParams(
        (previous) => {
          const updated = new URLSearchParams(previous)
          updated.delete('filters')
          next.forEach((filter) => updated.append('filters', filter))
          updated.delete('offset')
          return updated
        },
        { replace: true },
      )
    },
    [activeFilters, setSearchParams],
  )
  const clearFilters = useCallback(() => {
    setActiveFilters([])
    setSearchParams(
      (previous) => {
        const updated = new URLSearchParams(previous)
        updated.delete('filters')
        updated.delete('offset')
        return updated
      },
      { replace: true },
    )
  }, [setSearchParams])
  const changePeriod = (next: ClipPeriod) => {
    setPeriod(next)
    setSearchParams(
      (previous) => {
        const updated = new URLSearchParams(previous)
        if (next === 'week') updated.delete('period')
        else updated.set('period', next)
        updated.delete('offset')
        return updated
      },
      { replace: true },
    )
  }

  useResetOffsetOn(setOffset, [debouncedSearch, period, activeFilters, sort])

  const filterOptionsQuery = useQuery({
    queryKey: ['media', 'filters', section],
    queryFn: () => listMediaFilterOptions(section),
    staleTime: 60 * 60_000,
  })
  const availableFilters = [
    ...(filterOptionsQuery.data?.games ?? []),
    ...(isClips ? (filterOptionsQuery.data?.creators ?? []) : []),
    ...(isClips ? (filterOptionsQuery.data?.streams ?? []) : []),
  ] satisfies FilterOption[]
  const filterKeys = new Set(availableFilters.map((filter) => filter.key))
  const filters: FilterOption[] = [
    ...availableFilters,
    ...activeFilters
      .filter((key) => !filterKeys.has(key))
      .map((key) => {
        const [kind, id] = key.split(':', 2)
        const label =
          kind === 'game'
            ? `Игра #${id}`
            : kind === 'creator'
              ? `Автор #${id}`
              : kind === 'stream'
                ? `Стрим #${id}`
                : key
        return { key, label }
      }),
  ]

  const query = useQuery({
    queryKey: ['media', section, debouncedSearch, period, sort, offset],
    queryFn: async () => {
      if (isClips) {
        return {
          kind: 'clips' as const,
          page: await listClips({
            period,
            search: debouncedSearch || undefined,
            sort,
            direction: 'desc',
            limit: PAGE_SIZE,
            offset,
            filters: activeFilters,
          }),
        }
      }
      return {
        kind: 'recordings' as const,
        page: await listRecordings({
            search: debouncedSearch || undefined,
            sort,
            direction: 'desc',
            limit: PAGE_SIZE,
            offset,
            filters: activeFilters,
          }),
      }
    },
    staleTime: 60_000,
  })

  const title = isClips ? 'Клипы' : 'Записи'
  const page = query.data?.page

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <SectionHeader
        title={title}
        subtitle={
          page
            ? `Показано ${formatNumber(page.total)} из ${formatNumber(page.total_all ?? page.total)}`
            : 'Моменты с Twitch'
        }
        stats={
          page ? (
            <div className="flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.03] px-3 py-1 text-xs text-[var(--text-muted)]">
              <Eye className="h-3.5 w-3.5 text-[var(--accent)]" />
              {isClips ? 'Сначала популярные' : 'Записи стримов'}
            </div>
          ) : undefined
        }
      >
        {isClips ? (
          <div className="flex items-center gap-1 rounded-md border border-white/10 bg-[var(--card-bg)] p-1">
            <CalendarDays className="ml-1 h-4 w-4 text-[var(--text-muted)]" />
            {CLIP_PERIODS.map((item) => (
              <button
                key={item.key}
                type="button"
                onClick={() => changePeriod(item.key)}
                className={
                  period === item.key
                    ? 'rounded px-2 py-1 text-xs text-black [background:var(--accent)]'
                    : 'rounded px-2 py-1 text-xs text-[var(--text-muted)] hover:text-[var(--text)]'
                }
              >
                {item.label}
              </button>
            ))}
          </div>
        ) : null}
        {!isClips && canEdit ? (
          <button
            type="button"
            onClick={() => setEditMode((current) => !current)}
            className={
              editMode
                ? 'inline-flex items-center gap-1.5 rounded-md bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-black'
                : 'inline-flex items-center gap-1.5 rounded-md border border-white/15 px-3 py-1.5 text-sm text-[var(--text-muted)] hover:bg-white/5 hover:text-[var(--text)]'
            }
          >
            <Pencil className="h-4 w-4" />
            {editMode ? 'Готово' : 'Редактирование'}
          </button>
        ) : null}
        <label className="flex items-center gap-2">
          <ArrowDownWideNarrow className="h-4 w-4 text-[var(--text-muted)]" />
          <select
            value={sort}
            onChange={(event) => setSort(event.target.value as MediaSort)}
            className="rounded-md border border-white/15 bg-[var(--card-bg)] px-2 py-1.5 text-xs text-[var(--text)] outline-none focus:border-[var(--accent)]"
            aria-label="Сортировка"
          >
            {isClips ? <option value="views">По просмотрам</option> : null}
            <option value="date">Сначала новые</option>
            <option value="title">По названию</option>
            <option value="duration">По длительности</option>
          </select>
        </label>
        <FilterMenu
          options={filters}
          active={activeFilters}
          onToggle={toggleFilter}
          onClear={clearFilters}
        />
        <SearchInput
          value={search}
          onChange={setSearch}
          placeholder={isClips ? 'Поиск по клипам...' : 'Поиск по записям...'}
          className="w-full sm:w-64"
        />
      </SectionHeader>

      {query.isPending ? (
        <div className="grid flex-1 grid-cols-1 gap-3 p-3 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-5">
          {Array.from({ length: 8 }).map((_, index) => (
            <div key={index} className="overflow-hidden rounded-xl border border-white/10">
              <Skeleton className="aspect-video rounded-none" />
              <div className="space-y-3 p-4">
                <Skeleton className="h-4 w-4/5" />
                <Skeleton className="h-3 w-2/3" />
              </div>
            </div>
          ))}
        </div>
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={() => void query.refetch()} />
      ) : page?.items.length ? (
        <>
          <div className="grid grid-cols-1 gap-3 p-3 sm:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-5">
            {page.items.map((item) => (
              <MediaCard
                key={item.id}
                item={item}
                onPlay={setSelectedItem}
                onEditPreview={
                  editMode && 'twitch_video_id' in item
                    ? () => setEditingRecording(item)
                    : undefined
                }
              />
            ))}
          </div>
          {selectedItem ? (
            <MediaPlayerModal
              item={selectedItem}
              onClose={() => setSelectedItem(null)}
            />
          ) : null}
          {editingRecording ? (
            <RecordingPreviewEditModal
              recording={editingRecording}
              onClose={() => setEditingRecording(null)}
            />
          ) : null}
          <Pagination
            total={page.total}
            limit={PAGE_SIZE}
            offset={offset}
            onChange={setOffset}
          />
        </>
      ) : (
        <EmptyState
          title={isClips ? 'Клипов за этот период пока нет' : 'Доступных записей пока нет'}
          hint="Данные обновляются из Twitch и появятся здесь после синхронизации."
        />
      )}
    </div>
  )
}
