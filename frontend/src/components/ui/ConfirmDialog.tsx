import { useEffect } from 'react'

import { cn } from '@/lib/cn'

/**
 * Простой модальный диалог подтверждения (тёмный фон, Escape/фон — отмена).
 * Кнопка подтверждения — красная (деструктивное действие).
 */
export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = 'Удалить',
  onConfirm,
  onCancel,
  busy = false,
}: {
  open: boolean
  title: string
  message?: string
  confirmLabel?: string
  onConfirm: () => void
  onCancel: () => void
  busy?: boolean
}) {
  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onCancel()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onCancel])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onCancel}
    >
      <div
        onClick={(event) => event.stopPropagation()}
        className="w-full max-w-sm overflow-hidden rounded-lg border border-white/10 bg-[var(--card-bg)] shadow-xl shadow-black/40"
      >
        <div className="px-5 py-4">
          <h2 className="text-sm font-medium text-[var(--text)]">{title}</h2>
          {message ? (
            <p className="mt-2 text-sm leading-snug text-[var(--text-muted)]">
              {message}
            </p>
          ) : null}
        </div>
        <div className="flex justify-end gap-2 border-t border-white/10 px-5 py-3">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md border border-white/15 px-3 py-1.5 text-sm text-[var(--text)] transition-colors hover:bg-white/5"
          >
            Отмена
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={onConfirm}
            className={cn(
              'rounded-md bg-red-500/90 px-3 py-1.5 text-sm font-medium text-white',
              'transition-colors hover:bg-red-500 disabled:opacity-40',
            )}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
