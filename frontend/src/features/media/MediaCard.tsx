import { Clock3, Eye, ExternalLink, Pencil, Play } from 'lucide-react'
import { Link } from 'react-router-dom'

import type { ClipView, RecordingView } from '@/api/types'
import { formatDateTime, formatHoursMinutes, formatNumber } from '@/lib/format'

export type MediaItem = ClipView | RecordingView

function isClip(item: MediaItem): item is ClipView {
  return 'external_id' in item
}

function formatClipDuration(seconds: number | null): string {
  if (seconds === null || seconds === undefined) return '—'
  const minutes = Math.floor(seconds / 60)
  const remainder = seconds % 60
  return minutes ? `${minutes}:${String(remainder).padStart(2, '0')}` : `${seconds} сек`
}

export function MediaCard({
  item,
  onPlay,
  onEditPreview,
}: {
  item: MediaItem
  onPlay: (item: MediaItem) => void
  onEditPreview?: () => void
}) {
  const clip = isClip(item)
  const thumbnail = item.thumbnail_url
  const twitchVideoId =
    !clip && !item.twitch_video_id
      ? item.url.match(/\/videos\/(\d+)/)?.[1] ?? null
      : !clip
        ? item.twitch_video_id
        : null

  const games = clip
    ? item.game_id && item.game_name
      ? [{ id: item.game_id, name: item.game_name }]
      : []
    : item.game_refs
  const showStreamTitle =
    Boolean(item.stream_title) &&
    item.stream_title?.trim() !== item.title.trim()
  const duration = clip
    ? formatClipDuration(item.duration_seconds)
    : formatHoursMinutes(item.duration_minutes)

  return (
    <article className="overflow-hidden rounded-xl border border-white/10 bg-[var(--card-bg)] shadow-lg shadow-black/10">
      <button
        type="button"
        onClick={() => {
          if (clip || twitchVideoId) onPlay(item)
          else window.open(item.url, '_blank', 'noopener,noreferrer')
        }}
        className="group relative block aspect-video w-full overflow-hidden bg-black/30 text-white"
        aria-label={`Смотреть: ${item.title}`}
      >
        {thumbnail ? (
          <img
            src={thumbnail}
            alt=""
            loading="lazy"
            className="absolute inset-0 h-full w-full object-cover transition-transform duration-300 group-hover:scale-[1.03]"
          />
        ) : null}
        <span className="absolute inset-0 bg-black/25 transition-colors group-hover:bg-black/40" />
        <span className="relative flex h-full w-full items-center justify-center">
          <span className="flex h-14 w-14 items-center justify-center rounded-full bg-[var(--accent)] text-black shadow-lg transition-transform group-hover:scale-110">
            <Play className="ml-1 h-6 w-6 fill-current" />
          </span>
        </span>
        {duration !== '—' ? (
          <span className="absolute bottom-2 right-2 rounded bg-black/75 px-2 py-1 text-xs">
            {duration}
          </span>
        ) : null}
      </button>

      <div className="space-y-2.5 p-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <button
              type="button"
              onClick={() => {
                if (clip || twitchVideoId) onPlay(item)
                else window.open(item.url, '_blank', 'noopener,noreferrer')
              }}
              className="line-clamp-2 text-left text-sm font-semibold text-[var(--text)] transition-colors hover:text-[var(--accent)]"
            >
              {item.title}
            </button>
            {showStreamTitle ? (
              <p className="mt-1 line-clamp-1 text-xs text-[var(--text-muted)]">
                {item.stream_title}
              </p>
            ) : null}
          </div>
          <div className="flex shrink-0 items-center">
            {onEditPreview ? (
              <button
                type="button"
                onClick={onEditPreview}
                className="rounded-md p-1.5 text-[var(--text-muted)] transition-colors hover:text-[var(--accent)]"
                aria-label="Редактировать превью"
                title="Редактировать превью"
              >
                <Pencil className="h-4 w-4" />
              </button>
            ) : null}
            <a
              href={item.url}
              target="_blank"
              rel="noreferrer"
              className="rounded-md p-1.5 text-[var(--text-muted)] transition-colors hover:text-[var(--accent)]"
              aria-label="Открыть на Twitch"
              title="Открыть на Twitch"
            >
              <ExternalLink className="h-4 w-4" />
            </a>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-[var(--text-muted)]">
          <span className="inline-flex items-center gap-1">
            <Eye className="h-3.5 w-3.5" />
            {formatNumber(item.views_count)}
          </span>
          <span className="inline-flex items-center gap-1">
            <Clock3 className="h-3.5 w-3.5" />
            {duration}
          </span>
          <Link
            to={`/streams?stream_id=${item.stream_id}`}
            className="truncate transition-colors hover:text-[var(--accent)] hover:underline"
            title="Открыть этот стрим"
          >
            {formatDateTime(clip ? item.created_at : item.recorded_at)}
          </Link>
        </div>

        <div className="flex flex-wrap gap-1.5">
          {games.map((game) => (
            <Link
              key={game.id}
              to={`/games/${game.id}`}
              className="rounded-full border border-[color-mix(in_srgb,var(--accent)_25%,transparent)] px-2 py-0.5 text-[11px] text-[var(--accent)] transition-colors hover:bg-white/[0.06]"
            >
              {game.name}
            </Link>
          ))}
          {clip && item.creator_display_name ? (
            <span className="rounded-full bg-white/[0.05] px-2 py-0.5 text-[11px] text-[var(--text-muted)]">
              {item.creator_display_name}
            </span>
          ) : null}
        </div>
      </div>
    </article>
  )
}
