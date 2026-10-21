import type { SelectHTMLAttributes } from 'react'

import { cn } from '@/lib/cn'

export function Select({
  className,
  children,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      className={cn(
        'rounded-md border border-white/15 bg-[var(--card-bg)] px-2.5 py-1.5 text-sm text-[var(--text)] outline-none transition-colors focus:border-[var(--accent)]',
        className,
      )}
    >
      {children}
    </select>
  )
}
