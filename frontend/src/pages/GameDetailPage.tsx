import { useState } from 'react'
import type { ReactNode } from 'react'
import { ArrowLeft, ExternalLink } from 'lucide-react'
import { Link, useParams } from 'react-router-dom'

import { SectionHeader } from '@/components/layout/SectionHeader'
import { SectionPanel } from '@/components/layout/SectionPanel'
import { ErrorState } from '@/components/ui/ErrorState'
import { FlagToggle } from '@/components/ui/FlagToggle'
import { GameDetailSkeleton } from '@/pages/GameDetailSkeleton'
import { useAuth } from '@/features/auth/context'
import { useGame, useGameStreams, useUpdateGameState } from '@/features/games/useGames'
import { useSetReleaseInterested } from '@/features/releases/useReleases'
import {
  formatDateNumeric,
  formatDuration,
  formatHltbTime,
  formatNumber,
  formatReleaseCountdown,
  isReleased,
} from '@/lib/format'
import { GAME_COVER_PLACEHOLDER } from '@/lib/games'
import { normalizeTag } from '@/lib/tags'

/** Акценты разделов «Статистики» — цвет разделительных полос. */
const ACCENT = {
  games: 'var(--accent-games)',
  streams: 'var(--accent-streams)',
  releases: 'var(--accent-releases)',
  recommendations: 'var(--accent-recommendations)',
  hltb: 'var(--accent-hltb)',
} as const

const HLTB_URL = 'https://howlongtobeat.com/game/'

/** Сколько стримов по игре догружаем за раз. */
const STREAMS_PAGE = 50

/** Строка колонки: подпись слева, значение справа, полоса-разделитель снизу. */
function Row({
  label,
  value,
  accent,
}: {
  label: string
  value: ReactNode
  accent: string
}) {
  return (
    <div
      className="flex items-baseline justify-between gap-4 border-b py-2"
      style={{ borderColor: `color-mix(in srgb, ${accent} 35%, transparent)` }}
    >
      <dt className="shrink-0 text-xs uppercase tracking-wide text-[var(--text-muted)]">
        {label}
      </dt>
      <dd className="min-w-0 text-right text-sm text-[var(--text)]">{value}</dd>
    </div>
  )
}

/** Небольшой заголовок блока в цвете раздела. */
function BlockTitle({ children, accent }: { children: ReactNode; accent: string }) {
  return (
    <h2
      className="mb-2 border-b-2 pb-1.5 text-xs font-semibold uppercase tracking-wider"
      style={{ borderColor: accent, color: accent }}
    >
      {children}
    </h2>
  )
}

/** Внешняя ссылка с значком «уходит наружу». */
function OutLink({
  href,
  children,
  className,
}: {
  href: string
  children: ReactNode
  className: string
}) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className={`inline-flex items-center gap-1 transition-opacity hover:opacity-80 ${className}`}
    >
      {children}
      <ExternalLink className="h-3.5 w-3.5 shrink-0" />
    </a>
  )
}

export function GameDetailPage() {
  const { gameId } = useParams()
  const id = Number(gameId)
  const query = useGame(id)
  const { canEdit } = useAuth()
  const stateMutation = useUpdateGameState()
  const interestedMutation = useSetReleaseInterested()

  // Стримы по игре грузим порциями: сначала 50, дальше по кнопке.
  const [streamsLimit, setStreamsLimit] = useState(STREAMS_PAGE)
  const moreStreams = useGameStreams(
    id,
    { limit: streamsLimit, offset: 0 },
    query.isSuccess && (query.data?.streams_total ?? 0) > streamsLimit,
  )
  const streams = moreStreams.data?.items ?? query.data?.streams ?? []
  const streamsTotal = query.data?.streams_total ?? streams.length

  const game = query.data

  const setLiked = (liked: boolean) => {
    if (!game) return
    stateMutation.mutate({ gameId: game.id, liked, completed: game.completed })
  }
  const setCompleted = (completed: boolean) => {
    if (!game) return
    stateMutation.mutate({ gameId: game.id, liked: game.liked, completed })
  }
  const setInterested = (interested: boolean) => {
    if (!game) return
    interestedMutation.mutate({ gameId: game.id, interested })
  }

  const description = game?.description_ru || game?.description_en || ''
  const countdown = formatReleaseCountdown(game?.release_date)
  const released = isReleased(game?.release_date)

  const hltbRows: Array<{ label: string; value: number | null | undefined }> = game
    ? [
        { label: 'Все стили', value: game.hltb_all_styles },
        { label: 'Сюжет', value: game.hltb_main_story },
        { label: 'Сюжет+Доп', value: game.hltb_main_extra },
        { label: 'Полное', value: game.hltb_completionist },
        { label: 'Кооп', value: game.hltb_coop },
        { label: 'Мультиплеер', value: game.hltb_multiplayer },
      ]
    : []
  const hltbFilled = hltbRows.filter(
    (row) => row.value !== null && row.value !== undefined,
  )

  return (
    <div data-section="games" className="flex flex-1 flex-col bg-[var(--section-bg)]">
      <div className="flex flex-1">
        <SectionPanel />
        <div className="flex flex-1 flex-col">
          <SectionHeader title="Страница игры">
            {game?.in_games ? (
              <Link
                to="/games"
                className="font-social text-xs uppercase tracking-wider text-[var(--text-muted)] transition-colors hover:text-[var(--accent-games)]"
              >
                Все игры
              </Link>
            ) : null}
            {game?.in_releases ? (
              <Link
                to="/releases"
                className="font-social text-xs uppercase tracking-wider text-[var(--text-muted)] transition-colors hover:text-[var(--accent-releases)]"
              >
                Все релизы
              </Link>
            ) : null}
            {game?.in_recommendations ? (
              <Link
                to="/recommendations"
                className="font-social text-xs uppercase tracking-wider text-[var(--text-muted)] transition-colors hover:text-[var(--accent-recommendations)]"
              >
                Все советы
              </Link>
            ) : null}
            <Link
              to="/games"
              className="flex items-center gap-1 text-sm text-[var(--text-muted)] transition-colors hover:text-[var(--text)]"
            >
              <ArrowLeft className="h-4 w-4" />
            </Link>
          </SectionHeader>

          {query.isLoading ? (
            <GameDetailSkeleton />
          ) : query.isError ? (
            <ErrorState error={query.error} onRetry={() => void query.refetch()} />
          ) : game ? (
            <div className="grid grid-cols-1 gap-6 p-6 lg:grid-cols-3">
              {/* Первый столбик — общая информация и показатели. */}
              <div className="flex flex-col bg-[var(--card-bg)] px-4 py-4">
                <div className="mb-4 flex items-start gap-3">
                  <img
                    src={game.cover_url || GAME_COVER_PLACEHOLDER}
                    alt=""
                    className="h-[45px] w-[45px] shrink-0 rounded-lg border border-white/10 object-cover"
                    onError={(event) => {
                      event.currentTarget.src = GAME_COVER_PLACEHOLDER
                    }}
                  />
                  <h1 className="font-sans text-2xl leading-tight text-[var(--text)]">
                    {game.name}
                  </h1>
                </div>

                {description ? (
                  <p className="mb-3 text-sm leading-relaxed text-[var(--text)]">
                    {description}
                  </p>
                ) : null}

                {game.steam_url || game.hltb_id ? (
                  <div className="mb-3 flex flex-wrap items-center gap-4">
                    {game.steam_url ? (
                      <OutLink
                        href={game.steam_url}
                        className="font-social text-sm text-[#66c0f4]"
                      >
                        Steam
                      </OutLink>
                    ) : null}
                    {game.hltb_id ? (
                      <OutLink
                        href={`${HLTB_URL}${game.hltb_id}`}
                        className="font-social text-sm text-[var(--accent-hltb)]"
                      >
                        HowLongToBeat
                      </OutLink>
                    ) : null}
                  </div>
                ) : null}

                <Row
                  label="Дата релиза"
                  accent={ACCENT.releases}
                  value={
                    game.release_date ? (
                      <span className="flex flex-col items-end">
                        <span>{formatDateNumeric(game.release_date)}</span>
                        <span className="text-xs text-[var(--text-muted)]">
                          {released
                            ? 'Вышел'
                            : countdown
                              ? `Через ${countdown}`
                              : 'Скоро'}
                        </span>
                      </span>
                    ) : (
                      '—'
                    )
                  }
                />
                <Row
                  label="Жанры"
                  accent={ACCENT.games}
                  value={
                    game.genres.length ? game.genres.map(normalizeTag).join(', ') : '—'
                  }
                />
                <Row
                  label="Платформы"
                  accent={ACCENT.games}
                  value={game.platforms.length ? game.platforms.join(', ') : '—'}
                />
                <Row label="Ранг" accent={ACCENT.games} value={`#${game.rank}`} />
                <Row
                  label="Часов"
                  accent={ACCENT.games}
                  value={formatDuration(game.duration_minutes, game.hours)}
                />

                {game.in_games || game.in_releases ? (
                  <div className="mt-6">
                    {game.in_games ? (
                      <>
                        <Row
                          label="Пройдено"
                          accent={ACCENT.games}
                          value={
                            <FlagToggle
                              value={game.completed}
                              label="Пройдено"
                              onChange={canEdit ? setCompleted : undefined}
                              busy={stateMutation.isPending}
                            />
                          }
                        />
                        <Row
                          label="Понравилось"
                          accent={ACCENT.games}
                          value={
                            <FlagToggle
                              value={game.liked}
                              label="Понравилось"
                              onChange={canEdit ? setLiked : undefined}
                              busy={stateMutation.isPending}
                            />
                          }
                        />
                      </>
                    ) : null}

                    {game.in_releases ? (
                      <Row
                        label="Интересно"
                        accent={ACCENT.releases}
                        value={
                          <FlagToggle
                            value={game.interested}
                            label="Интересно"
                            onChange={canEdit ? setInterested : undefined}
                            busy={interestedMutation.isPending}
                          />
                        }
                      />
                    ) : null}
                  </div>
                ) : null}
              </div>

              {/* Второй столбик — стримы, от новейших к самым старым. */}
              <div className="flex flex-col bg-[var(--card-bg)] px-4 py-4">
                <BlockTitle accent={ACCENT.streams}>
                  Стримы ({formatNumber(streamsTotal)})
                </BlockTitle>
                {streams.length ? (
                  <>
                    <ul className="overflow-y-auto pr-1 lg:max-h-[70vh]">
                      {streams.map((stream) => (
                        <li
                          key={stream.id}
                          className="flex items-baseline justify-between gap-3 border-b py-2 last:border-b-0"
                          style={{
                            borderColor: `color-mix(in srgb, ${ACCENT.streams} 25%, transparent)`,
                          }}
                        >
                          <span className="flex min-w-0 items-baseline gap-2">
                            <span className="shrink-0 text-xs text-[var(--text-muted)]">
                              {stream.started_at
                                ? formatDateNumeric(stream.started_at)
                                : '—'}
                            </span>
                            <span className="min-w-0 truncate text-sm text-[var(--text)]">
                              {stream.title || '—'}
                            </span>
                          </span>
                          <span className="flex shrink-0 items-baseline gap-2">
                            <span className="text-xs text-[var(--text-muted)]">
                              {formatDuration(
                                stream.duration_minutes,
                                (stream.duration_minutes ?? 0) / 60,
                              )}
                            </span>
                            {stream.vod_url ? (
                              <a
                                href={stream.vod_url}
                                target="_blank"
                                rel="noreferrer"
                                title="Запись стрима"
                                className="text-[var(--text-muted)] transition-colors hover:text-[var(--accent-streams)]"
                              >
                                <ExternalLink className="h-3.5 w-3.5" />
                              </a>
                            ) : null}
                          </span>
                        </li>
                      ))}
                    </ul>
                    {streams.length < streamsTotal ? (
                      <button
                        type="button"
                        onClick={() => setStreamsLimit((value) => value + STREAMS_PAGE)}
                        disabled={moreStreams.isFetching}
                        className="mt-3 w-full rounded-md border border-white/15 px-3 py-1.5 text-sm text-[var(--text)] transition-colors hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {moreStreams.isFetching
                          ? 'Загружаем…'
                          : `Показать ещё (${formatNumber(streamsTotal - streams.length)})`}
                      </button>
                    ) : null}
                  </>
                ) : (
                  <p className="text-sm text-[var(--text-muted)]">
                    По этой игре стримов не было.
                  </p>
                )}
              </div>

              {/* Третий столбик — время прохождения и рекомендации. */}
              <div className="flex flex-col bg-[var(--card-bg)] px-4 py-4">
                {hltbFilled.length ? (
                  <>
                    <BlockTitle accent={ACCENT.hltb}>Время прохождения</BlockTitle>
                    {hltbFilled.map((row) => (
                      <Row
                        key={row.label}
                        label={row.label}
                        accent={ACCENT.hltb}
                        value={formatHltbTime(row.value)}
                      />
                    ))}
                  </>
                ) : null}

                {!game.in_games ? (
                  <div className={hltbFilled.length ? 'mt-6' : ''}>
                    <BlockTitle accent={ACCENT.recommendations}>Рекомендуют</BlockTitle>
                    {game.recommenders_list.length ? (
                      <ul>
                        {game.recommenders_list.map((rec) => (
                          <li
                            key={rec.user_login ?? rec.display_name}
                            className="flex items-baseline justify-between gap-3 border-b py-2 last:border-b-0"
                            style={{
                              borderColor: `color-mix(in srgb, ${ACCENT.recommendations} 25%, transparent)`,
                            }}
                            title={rec.recommendation_note ?? undefined}
                          >
                            <span className="text-sm text-[var(--text)]">
                              {rec.display_name || rec.user_login}
                            </span>
                            {rec.recommendation_note ? (
                              <span className="truncate text-xs text-[var(--text-muted)]">
                                {rec.recommendation_note}
                              </span>
                            ) : null}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p className="text-sm text-[var(--text-muted)]">
                        Пока никто не рекомендовал.
                      </p>
                    )}
                  </div>
                ) : null}
              </div>
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}
