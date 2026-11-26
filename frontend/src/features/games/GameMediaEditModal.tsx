import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { ImagePlus, Save, Trash2, X } from 'lucide-react'
import { toast } from 'sonner'

import {
  deleteGameCover,
  setGameCoverUrl,
  updateGameIGDBId,
  uploadGameCover,
} from '@/features/games/api'
import { cn } from '@/lib/cn'

export function GameMediaEditModal({
  gameId,
  gameName,
  coverUrl,
  currentIgdbId,
  onClose,
}: {
  gameId: number
  gameName: string
  coverUrl: string | null
  currentIgdbId: string | null
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [coverLink, setCoverLink] = useState('')
  const [igdbId, setIgdbId] = useState(currentIgdbId ?? '')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busy) onClose()
    }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [busy, onClose])

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['games'] })
    void queryClient.invalidateQueries({ queryKey: ['releases'] })
    void queryClient.invalidateQueries({ queryKey: ['recommendations'] })
  }

  const run = async (action: () => Promise<unknown>, success: string) => {
    if (busy) return
    setBusy(true)
    try {
      await action()
      invalidate()
      toast.success(success)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось сохранить.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className="fixed inset-0 z-[90] flex items-center justify-center bg-black/70 p-3"
      onClick={() => {
        if (!busy) onClose()
      }}
    >
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="game-media-editor-title"
        onClick={(event) => event.stopPropagation()}
        className="max-h-[94vh] w-full max-w-2xl overflow-y-auto rounded-xl border border-white/10 bg-[var(--card-bg)] shadow-2xl"
      >
        <header className="flex items-start justify-between gap-4 border-b border-white/10 p-4 sm:p-5">
          <div>
            <h2 id="game-media-editor-title" className="font-social text-sm uppercase">
              Редактирование игры
            </h2>
            <p className="mt-1 text-sm text-[var(--text-muted)]">{gameName}</p>
          </div>
          <button
            type="button"
            disabled={busy}
            onClick={onClose}
            className="rounded p-1.5 text-[var(--text-muted)] hover:text-[var(--text)] disabled:opacity-40"
            aria-label="Закрыть"
          >
            <X className="h-5 w-5" />
          </button>
        </header>

        <div className="space-y-6 p-4 sm:p-5">
          <section className="space-y-3">
            <h3 className="text-sm font-semibold text-[var(--text)]">Обложка</h3>
            {coverUrl ? (
              <img
                src={coverUrl}
                alt={`Обложка ${gameName}`}
                className="h-36 w-28 rounded-md border border-white/10 bg-black/20 object-cover"
              />
            ) : (
              <p className="text-xs text-[var(--text-muted)]">Обложка не задана.</p>
            )}
            <div className="flex flex-wrap gap-2">
              <input
                type="url"
                value={coverLink}
                onChange={(event) => setCoverLink(event.target.value)}
                placeholder="https://ссылка-на-обложку"
                className="min-w-56 flex-1 rounded-md border border-white/15 bg-[var(--section-bg)] px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-[var(--accent)]"
              />
              <button
                type="button"
                disabled={busy || !coverLink.trim()}
                onClick={() =>
                  void run(
                    () => setGameCoverUrl(gameId, coverLink.trim()),
                    'Обложка по ссылке сохранена.',
                  )
                }
                className="inline-flex items-center gap-1.5 rounded-md bg-[var(--accent)] px-3 py-2 text-sm font-medium text-black disabled:opacity-40"
              >
                <Save className="h-4 w-4" />
                Сохранить URL
              </button>
              <label
                className={cn(
                  'inline-flex cursor-pointer items-center gap-1.5 rounded-md border border-white/15 px-3 py-2 text-sm',
                  'text-[var(--text)] hover:bg-white/5',
                  busy && 'pointer-events-none opacity-40',
                )}
              >
                <ImagePlus className="h-4 w-4" />
                Загрузить файл
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/webp,image/gif"
                  className="hidden"
                  disabled={busy}
                  onChange={(event) => {
                    const file = event.target.files?.[0]
                    if (file) {
                      void run(
                        () => uploadGameCover(gameId, file),
                        'Обложка загружена.',
                      )
                    }
                    event.currentTarget.value = ''
                  }}
                />
              </label>
              <button
                type="button"
                disabled={busy}
                onClick={() =>
                  void run(() => deleteGameCover(gameId), 'Ручная обложка удалена.')
                }
                className="inline-flex items-center gap-1.5 rounded-md border border-red-400/20 px-3 py-2 text-sm text-red-300 hover:bg-red-400/10 disabled:opacity-40"
                title="Удалить ручную обложку; обложка IGDB может остаться"
              >
                <Trash2 className="h-4 w-4" />
                Удалить ручную
              </button>
            </div>
            <p className="text-xs text-[var(--text-muted)]">
              Ручная обложка отображается выше обложки IGDB. Удаление ручной обложки
              вернёт обложку IGDB, если она есть.
            </p>
          </section>

          <section className="space-y-3 border-t border-white/10 pt-5">
            <h3 className="text-sm font-semibold text-[var(--text)]">Связь с IGDB</h3>
            <div className="flex flex-wrap gap-2">
              <input
                value={igdbId}
                onChange={(event) => setIgdbId(event.target.value)}
                placeholder="IGDB ID"
                inputMode="numeric"
                className="min-w-40 flex-1 rounded-md border border-white/15 bg-[var(--section-bg)] px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-[var(--accent)]"
              />
              <button
                type="button"
                disabled={busy || !igdbId.trim()}
                onClick={() =>
                  void run(
                    () => updateGameIGDBId(gameId, igdbId.trim()),
                    'IGDB ID и метаданные обновлены.',
                  )
                }
                className="rounded-md bg-[var(--accent)] px-3 py-2 text-sm font-medium text-black disabled:opacity-40"
              >
                Сохранить и обновить
              </button>
              <button
                type="button"
                disabled={busy || !currentIgdbId}
                onClick={() =>
                  void run(
                    () => updateGameIGDBId(gameId, null),
                    'Связь с IGDB удалена; игра сохранена.',
                  )
                }
                className="rounded-md border border-red-400/20 px-3 py-2 text-sm text-red-300 hover:bg-red-400/10 disabled:opacity-40"
              >
                Удалить IGDB ID
              </button>
            </div>
            <p className="text-xs text-[var(--text-muted)]">
              Новый ID загружает свежие метаданные. Удаление удаляет только строку
              метаданных IGDB, сама игра и её ручная обложка остаются.
            </p>
          </section>
        </div>

        <footer className="flex justify-end border-t border-white/10 p-4">
          <button
            type="button"
            disabled={busy}
            onClick={onClose}
            className="rounded-md border border-white/15 px-4 py-2 text-sm text-[var(--text)] hover:bg-white/5 disabled:opacity-40"
          >
            Готово
          </button>
        </footer>
      </section>
    </div>
  )
}
