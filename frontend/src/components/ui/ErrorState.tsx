import { AlertTriangle } from 'lucide-react'

import { ApiError } from '@/lib/apiError'

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message =
    error instanceof ApiError ? error.message : 'Не удалось загрузить данные.'

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 p-10 text-center">
      <AlertTriangle className="h-7 w-7 text-red-400" />
      <p className="text-sm text-[var(--text-muted)]">{message}</p>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="rounded-md border border-white/15 px-3 py-1.5 text-sm text-[var(--text)] transition-colors hover:bg-white/5"
        >
          Повторить
        </button>
      ) : null}
    </div>
  )
}
