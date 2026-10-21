import { ChevronRight } from 'lucide-react'
import { Link } from 'react-router-dom'

import { cn } from '@/lib/cn'
import { GAME_COVER_PLACEHOLDER, normalizeGameName } from '@/lib/games'
import type { GameRef } from '@/lib/games'

/** Сколько обложек помещается в одну строку полосы. */
const PER_ROW = 6

/**
 * Полоса обложек игр, сыгранных на стриме.
 *
 * Обложки квадратные (45×45) и умещаются по шесть в ряд; между играми
 * внутри строки — тонкая шеврон-стрелка в промежутке.
 */
export function GameCoverStrip({
  names,
  gamesByName,
  className,
}: {
  names: string[]
  gamesByName: Map<string, GameRef>
  className?: string
}) {
  if (names.length === 0) {
    return <span className="text-[var(--text-muted)]">—</span>
  }
  return (
    <span className={cn('grid grid-cols-6 gap-4', className)}>
      {names.map((name, index) => {
        const game = gamesByName.get(normalizeGameName(name))
        const cover = (
          <img
            src={game?.coverUrl ?? GAME_COVER_PLACEHOLDER}
            alt={name}
            loading="lazy"
            className="h-[45px] w-[45px] shrink-0 rounded-lg object-cover"
            onError={(event) => {
              const img = event.currentTarget
              if (!img.dataset.fallback) {
                img.dataset.fallback = '1'
                img.src = GAME_COVER_PLACEHOLDER
              }
            }}
          />
        )
        return (
          <span key={`${name}-${index}`} className="relative flex items-center">
            {index % PER_ROW !== 0 ? (
              <ChevronRight
                aria-hidden
                className="absolute -left-[15px] h-3.5 w-3.5 text-[var(--text-muted)] opacity-60"
              />
            ) : null}
            {game ? (
              <Link
                to={`/games/${game.id}`}
                title={name}
                className="shrink-0 transition-opacity hover:opacity-80"
              >
                {cover}
              </Link>
            ) : (
              <span title={name} className="shrink-0">
                {cover}
              </span>
            )}
          </span>
        )
      })}
    </span>
  )
}
