import type { ButtonHTMLAttributes } from 'react'

import { cn } from '@/lib/cn'

type ButtonVariant = 'primary' | 'ghost' | 'subtle'
type ButtonSize = 'sm' | 'md'

const VARIANTS: Record<ButtonVariant, string> = {
  primary: 'bg-[var(--accent)] text-black font-medium enabled:hover:opacity-90',
  ghost: 'border border-white/15 text-[var(--text)] enabled:hover:bg-white/5',
  subtle:
    'text-[var(--text-muted)] enabled:hover:text-[var(--text)] enabled:hover:bg-white/5',
}

const SIZES: Record<ButtonSize, string> = {
  sm: 'px-2.5 py-1 text-xs',
  md: 'px-3 py-1.5 text-sm',
}

/** Простая кнопка в стиле интерфейса. */
export function Button({
  variant = 'ghost',
  size = 'md',
  className,
  type = 'button',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant
  size?: ButtonSize
}) {
  return (
    <button
      type={type}
      className={cn(
        'inline-flex items-center justify-center gap-1.5 rounded-md transition-colors',
        'disabled:cursor-not-allowed disabled:opacity-40',
        VARIANTS[variant],
        SIZES[size],
        className,
      )}
      {...props}
    />
  )
}
