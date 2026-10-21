import { Check } from 'lucide-react'

import { cn } from '@/lib/cn'

/**
 * Переключатель-«галочка» для булевых отметок (Понравилось / Пройдено /
 * Интересно).
 *
 * Без прав — статичная иконка (пользователь только смотрит). С правами —
 * кнопка с `aria-pressed`, клик переключает значение.
 */
export function FlagToggle({
  value,
  onChange,
  label,
  disabled = false,
  busy = false,
}: {
  /** Текущее значение отметки. */
  value: boolean
  /** Обработчик изменения; `undefined` — переключать нельзя. */
  onChange?: (next: boolean) => void
  /** Подпись для скринридера и тултипа. */
  label: string
  /** Временно недоступно (например, идёт запрос). */
  disabled?: boolean
  /** Идёт сохранение — показываем приглушённое состояние. */
  busy?: boolean
}) {
  const readOnly = !onChange

  if (readOnly) {
    return value ? (
      <span title={label} aria-label={label}>
        <Check className="h-4 w-4 text-[var(--accent)]" />
      </span>
    ) : (
      <span className="text-[var(--text-muted)]" title={label} aria-label={label}>
        —
      </span>
    )
  }

  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      aria-pressed={value}
      disabled={disabled || busy}
      onClick={(event) => {
        event.stopPropagation()
        onChange(!value)
      }}
      className={cn(
        'rounded-md p-1 transition-colors',
        disabled || busy ? 'cursor-wait opacity-60' : 'hover:bg-white/10',
      )}
    >
      {value ? (
        <Check className="h-4 w-4 text-[var(--accent)]" />
      ) : (
        <span className="block h-4 w-4 rounded-[4px] border border-white/20" />
      )}
    </button>
  )
}
