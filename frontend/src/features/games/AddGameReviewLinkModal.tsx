import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { X } from 'lucide-react'

import type { GameReviewLink } from '@/api/types'

export function AddGameReviewLinkModal({
  open,
  onClose,
  onSubmit,
}: {
  open: boolean
  onClose: () => void
  onSubmit: (link: GameReviewLink) => Promise<void>
}) {
  const [title, setTitle] = useState('Telegram')
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open || busy) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [open, onClose, busy])

  if (!open) return null

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const normalizedTitle = title.trim()
    const normalizedUrl = url.trim()
    if (!normalizedTitle || !normalizedUrl || busy) return
    setBusy(true)
    try {
      await onSubmit({ title: normalizedTitle, url: normalizedUrl })
      onClose()
    } catch {
      // Ошибку показывает React Query mutation.
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={() => {
        if (!busy) onClose()
      }}
    >
      <div
        onClick={(event) => event.stopPropagation()}
        className="w-full max-w-lg overflow-hidden rounded-lg border border-white/10 bg-[var(--card-bg)] shadow-xl shadow-black/40"
      >
        <div className="flex items-center justify-between border-b border-white/10 px-5 py-3">
          <h2 className="font-social text-sm uppercase tracking-wide text-[var(--text)]">
            Добавить отзыв
          </h2>
          <button
            type="button"
            onClick={onClose}
            disabled={busy}
            className="rounded-md p-1.5 text-[var(--text-muted)] transition-colors hover:text-[var(--text)] disabled:opacity-40"
            aria-label="Закрыть"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <form onSubmit={submit} className="space-y-4 px-5 py-4">
          <div className="space-y-1">
            <label
              htmlFor="game-review-title"
              className="block text-xs uppercase tracking-wide text-[var(--text-muted)]"
            >
              Название
            </label>
            <input
              id="game-review-title"
              autoFocus
              maxLength={80}
              value={title}
              onChange={(event) => setTitle(event.target.value)}
              className="w-full rounded-md border border-white/15 bg-[var(--section-bg)] px-3 py-1.5 text-sm text-[var(--text)] outline-none transition-colors focus:border-[var(--accent)]"
            />
          </div>

          <div className="space-y-1">
            <label
              htmlFor="game-review-url"
              className="block text-xs uppercase tracking-wide text-[var(--text-muted)]"
            >
              Ссылка
            </label>
            <input
              id="game-review-url"
              type="url"
              required
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              placeholder="https://..."
              className="w-full rounded-md border border-white/15 bg-[var(--section-bg)] px-3 py-1.5 text-sm text-[var(--text)] outline-none transition-colors placeholder:text-[var(--text-muted)] focus:border-[var(--accent)]"
            />
          </div>

          <div className="flex justify-end gap-2 border-t border-white/10 pt-3">
            <button
              type="button"
              onClick={onClose}
              disabled={busy}
              className="rounded-md border border-white/15 px-3 py-1.5 text-sm text-[var(--text)] transition-colors hover:bg-white/5 disabled:opacity-40"
            >
              Отмена
            </button>
            <button
              type="submit"
              disabled={busy || !title.trim() || !url.trim()}
              className="rounded-md bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-black transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {busy ? 'Добавление…' : 'Добавить'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
