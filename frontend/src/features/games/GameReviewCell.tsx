import { useState } from 'react'
import { Plus, X } from 'lucide-react'

import type { GameReviewLink } from '@/api/types'
import { AddGameReviewLinkModal } from '@/features/games/AddGameReviewLinkModal'

function serviceColor(url: string): string {
  let host = ''
  try {
    host = new URL(url).hostname.toLowerCase()
  } catch {
    return 'var(--text)'
  }

  if (host === 't.me' || host === 'telegram.me' || host.endsWith('.telegram.me')) {
    return 'var(--brand-telegram)'
  }
  if (host === 'twitch.tv' || host.endsWith('.twitch.tv')) {
    return 'var(--brand-twitch)'
  }
  if (host === 'youtube.com' || host === 'youtu.be' || host.endsWith('.youtube.com')) {
    return 'var(--brand-youtube)'
  }
  if (host === 'boosty.to' || host.endsWith('.boosty.to')) {
    return 'var(--brand-boosty)'
  }
  if (
    host === 'discord.gg' ||
    host === 'discord.com' ||
    host.endsWith('.discord.com')
  ) {
    return 'var(--brand-discord)'
  }
  return 'var(--text)'
}

export function GameReviewCell({
  links,
  editMode,
  busy,
  onSave,
}: {
  links: GameReviewLink[]
  editMode: boolean
  busy: boolean
  onSave: (links: GameReviewLink[]) => Promise<void>
}) {
  const [adding, setAdding] = useState(false)

  const remove = (index: number) => {
    void onSave(links.filter((_, linkIndex) => linkIndex !== index)).catch(() => {
      // Ошибку показывает React Query mutation.
    })
  }

  return (
    <>
      <span className="flex min-w-0 flex-wrap items-center gap-1">
        {links.map((link, index) => (
          <span key={`${link.url}-${index}`} className="inline-flex shrink-0 items-center gap-0.5">
            <a
              href={link.url}
              target="_blank"
              rel="noreferrer"
              title={link.url}
              className="max-w-32 truncate rounded-full bg-white/10 px-1.5 py-0.5 text-xs transition-colors hover:bg-white/20"
              style={{ color: serviceColor(link.url) }}
            >
              {link.title}
            </a>
            {editMode ? (
              <button
                type="button"
                aria-label={`Удалить ссылку ${link.title}`}
                title="Удалить ссылку"
                disabled={busy}
                onClick={() => remove(index)}
                className="shrink-0 rounded-full p-0.5 text-[var(--text-muted)] transition-colors hover:text-red-400 disabled:opacity-40"
              >
                <X className="h-3 w-3" />
              </button>
            ) : null}
          </span>
        ))}
        {editMode ? (
          <button
            type="button"
            onClick={() => setAdding(true)}
            title="Добавить отзыв"
            aria-label="Добавить отзыв"
            disabled={busy}
            className="shrink-0 rounded-full border border-dashed border-white/25 p-0.5 text-[var(--text-muted)] transition-colors hover:border-[var(--accent)] hover:text-[var(--accent)] disabled:opacity-40"
          >
            <Plus className="h-3.5 w-3.5" />
          </button>
        ) : null}
      </span>

      <AddGameReviewLinkModal
        key={adding ? 'open' : 'closed'}
        open={adding}
        onClose={() => setAdding(false)}
        onSubmit={async (link) => onSave([...links, link])}
      />
    </>
  )
}
