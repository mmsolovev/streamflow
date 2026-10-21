import { Inbox } from 'lucide-react'

export function EmptyState({
  title = 'Ничего не найдено',
  hint,
}: {
  title?: string
  hint?: string
}) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-2 p-10 text-center text-[var(--text-muted)]">
      <Inbox className="h-7 w-7" />
      <p className="text-sm">{title}</p>
      {hint ? <p className="text-xs opacity-70">{hint}</p> : null}
    </div>
  )
}
