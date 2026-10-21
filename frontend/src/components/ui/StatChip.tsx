import type { ReactNode } from 'react'

/**
 * «Сводка» в шапке раздела: крупная цифра над подписью, по центру.
 * Все чипы ряда — в одну строку.
 */
export function StatChip({ label, value }: { label: string; value: ReactNode }) {
  return (
    <span className="flex flex-col items-center rounded-full border border-white/10 bg-white/[0.03] px-3 py-1">
      <span className="text-lg font-semibold leading-tight text-[var(--accent)]">
        {value}
      </span>
      <span className="text-xs leading-tight text-[var(--text-muted)]">{label}</span>
    </span>
  )
}
