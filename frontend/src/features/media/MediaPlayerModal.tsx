import { useEffect } from 'react'
import { Clock3, ExternalLink, Eye, X } from 'lucide-react'
import { Link } from 'react-router-dom'

import type { ClipView } from '@/api/types'
import { formatDateTime, formatHoursMinutes, formatNumber } from '@/lib/format'
import type { MediaItem } from './MediaCard'

function isClip(item: MediaItem): item is ClipView {
  return 'external_id' in item
}

function getEmbedUrl(item: MediaItem): string | null {
  const parent = typeof window === 'undefined' ? 'localhost' : window.location.hostname
  if (isClip(item)) {
    const params = new URLSearchParams({
      clip: item.external_id,
      parent,
      autoplay: 'true',
      muted: 'true',
    })
    return `https://clips.twitch.tv/embed?${params.toString()}`
  }

  const videoId =
    item.twitch_video_id ?? item.url.match(/\/videos\/(\d+)/)?.[1] ?? null
  if (!videoId) return null
  const params = new URLSearchParams({
    video: `v${videoId}`,
    parent,
    autoplay: 'true',
    muted: 'true',
  })
  return `https://player.twitch.tv/?${params.toString()}`
}

function durationLabel(item: MediaItem): string {
  if (isClip(item)) {
    const seconds = item.duration_seconds
    if (seconds === null || seconds === undefined) return '—'
    const minutes = Math.floor(seconds / 60)
    const remainder = seconds % 60
    return minutes ? `${minutes}:${String(remainder).padStart(2, '0')}` : `${seconds} сек`
  }
  return formatHoursMinutes(item.duration_minutes)
}

export function MediaPlayerModal({
  item,
  onClose,
}: {
  item: MediaItem
  onClose: () => void
}) {
  const embedUrl = getEmbedUrl(item)
  const clip = isClip(item)
  const showStreamTitle =
    Boolean(item.stream_title) &&
    item.stream_title?.trim() !== item.title.trim()
  const games = clip
    ? item.game_id && item.game_name
      ? [{ id: item.game_id, name: item.game_name }]
      : []
    : item.game_refs

  useEffect(() => {
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.body.style.overflow = previousOverflow
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [onClose])

  if (!embedUrl) return null

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center bg-black/85 p-2 backdrop-blur-sm sm:p-5"
      onClick={onClose}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="media-player-title"
        className="max-h-[94vh] w-full max-w-7xl overflow-y-auto rounded-xl border border-white/10 bg-[var(--card-bg)] shadow-2xl shadow-black/60"
        onClick={(event) => event.stopPropagation()}
      >
        <header className="flex items-start justify-between gap-4 p-3 sm:p-4">
          <div className="min-w-0">
            <h2
              id="media-player-title"
              className="line-clamp-2 text-base font-semibold text-[var(--text)] sm:text-lg"
            >
              {item.title}
            </h2>
            {showStreamTitle ? (
              <p className="mt-1 line-clamp-1 text-sm text-[var(--text-muted)]">
                {item.stream_title}
              </p>
            ) : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="shrink-0 rounded-full bg-white/10 p-2 text-[var(--text)] transition-colors hover:bg-white/20"
            aria-label="Закрыть плеер"
            title="Закрыть"
          >
            <X className="h-5 w-5" />
          </button>
        </header>

        <div className="aspect-video w-full bg-black">
          <iframe
            src={embedUrl}
            title={item.title}
            className="h-full w-full border-0"
            allow="autoplay; fullscreen; picture-in-picture"
            allowFullScreen
          />
        </div>

        <footer className="flex flex-wrap items-center justify-between gap-3 p-3 sm:p-4">
          <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-sm text-[var(--text-muted)]">
            <span className="inline-flex items-center gap-1.5">
              <Eye className="h-4 w-4" />
              {formatNumber(item.views_count)}
            </span>
            <span className="inline-flex items-center gap-1.5">
              <Clock3 className="h-4 w-4" />
              {durationLabel(item)}
            </span>
            <Link
              to={`/streams?stream_id=${item.stream_id}`}
              onClick={onClose}
              className="transition-colors hover:text-[var(--accent)] hover:underline"
            >
              {formatDateTime(clip ? item.created_at : item.recorded_at)}
            </Link>
            {games.map((game) => (
              <Link
                key={game.id}
                to={`/games/${game.id}`}
                onClick={onClose}
                className="text-[var(--accent)] transition-opacity hover:opacity-80"
              >
                {game.name}
              </Link>
            ))}
          </div>
          <a
            href={item.url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 text-sm text-[var(--accent)] transition-opacity hover:opacity-80"
          >
            Открыть на Twitch
            <ExternalLink className="h-4 w-4" />
          </a>
        </footer>
      </section>
    </div>
  )
}
