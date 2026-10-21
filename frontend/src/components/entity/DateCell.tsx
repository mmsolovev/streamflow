import { formatDateNumeric, formatTime } from '@/lib/format'

/**
 * Ячейка даты: по центру, «ДД.ММ.ГГГГ», при наличии времени — второй строкой под датой.
 */
export function DateCell({
  iso,
  withTime = false,
}: {
  iso: string | null | undefined
  withTime?: boolean
}) {
  if (!iso) return <span className="text-[var(--text-muted)]">—</span>
  return (
    <span className="flex flex-col items-center leading-tight">
      <span>{formatDateNumeric(iso)}</span>
      {withTime ? <span>{formatTime(iso)}</span> : null}
    </span>
  )
}
