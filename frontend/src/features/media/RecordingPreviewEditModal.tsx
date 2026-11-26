import { useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { ImagePlus, Link2, Trash2, X } from 'lucide-react'
import { toast } from 'sonner'

import type { RecordingView } from '@/api/types'
import {
  deleteRecordingPreview,
  setRecordingPreviewUrl,
  uploadRecordingPreview,
} from '@/features/media/api'

export function RecordingPreviewEditModal({
  recording,
  onClose,
}: {
  recording: RecordingView
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busy) onClose()
    }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [busy, onClose])

  const run = async (action: () => Promise<unknown>, success: string) => {
    if (busy) return
    setBusy(true)
    try {
      await action()
      await queryClient.invalidateQueries({ queryKey: ['media', 'recordings'] })
      toast.success(success)
      onClose()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Не удалось сохранить превью.')
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
        aria-labelledby="recording-preview-title"
        onClick={(event) => event.stopPropagation()}
        className="w-full max-w-xl overflow-hidden rounded-xl border border-white/10 bg-[var(--card-bg)] shadow-2xl"
      >
        <header className="flex items-start justify-between gap-4 border-b border-white/10 p-4">
          <div className="min-w-0">
            <h2 id="recording-preview-title" className="font-social text-sm uppercase">
              Превью записи
            </h2>
            <p className="mt-1 line-clamp-2 text-sm text-[var(--text-muted)]">
              {recording.title}
            </p>
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

        <div className="space-y-4 p-4">
          {recording.thumbnail_url ? (
            <img
              src={recording.thumbnail_url}
              alt={`Превью ${recording.title}`}
              className="aspect-video w-full rounded-md border border-white/10 bg-black/20 object-contain"
            />
          ) : (
            <p className="rounded-md border border-dashed border-white/15 py-8 text-center text-sm text-[var(--text-muted)]">
              Превью пока нет
            </p>
          )}
          <div className="flex flex-wrap gap-2">
            <input
              type="url"
              value={url}
              onChange={(event) => setUrl(event.target.value)}
              placeholder="https://ссылка-на-изображение"
              className="min-w-48 flex-1 rounded-md border border-white/15 bg-[var(--section-bg)] px-3 py-2 text-sm text-[var(--text)] outline-none focus:border-[var(--accent)]"
            />
            <button
              type="button"
              disabled={busy || !url.trim()}
              onClick={() =>
                void run(
                  () => setRecordingPreviewUrl(recording.id, url.trim()),
                  'Превью по ссылке сохранено.',
                )
              }
              className="inline-flex items-center gap-1.5 rounded-md bg-[var(--accent)] px-3 py-2 text-sm font-medium text-black disabled:opacity-40"
            >
              <Link2 className="h-4 w-4" />
              Сохранить URL
            </button>
            <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-md border border-white/15 px-3 py-2 text-sm text-[var(--text)] hover:bg-white/5">
              <ImagePlus className="h-4 w-4" />
              Загрузить
              <input
                type="file"
                accept="image/png,image/jpeg,image/webp,image/gif"
                className="hidden"
                disabled={busy}
                onChange={(event) => {
                  const file = event.target.files?.[0]
                  if (file) {
                    void run(
                      () => uploadRecordingPreview(recording.id, file),
                      'Превью записи загружено.',
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
                void run(
                  () => deleteRecordingPreview(recording.id),
                  'Ручное превью удалено.',
                )
              }
              className="inline-flex items-center gap-1.5 rounded-md border border-red-400/20 px-3 py-2 text-sm text-red-300 hover:bg-red-400/10 disabled:opacity-40"
              title="После удаления будет показано превью Telegram или Twitch, если оно есть"
            >
              <Trash2 className="h-4 w-4" />
              Удалить ручное
            </button>
          </div>
          <p className="text-xs text-[var(--text-muted)]">
            Приоритет превью: ручное → фото анонса Telegram → Twitch. Удаление ручного
            варианта не удаляет автоматически найденное фото.
          </p>
        </div>
      </section>
    </div>
  )
}
