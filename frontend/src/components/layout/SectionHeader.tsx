import type { ReactNode } from 'react'

import { cn } from '@/lib/cn'

/** Функциональная полоса раздела: заголовок, сводка, поиск/фильтры, подсказка. */
export function SectionHeader({
  title,
  subtitle,
  stats,
  hint,
  action,
  noUppercase = false,
  plainTitle = false,
  titleAdornment,
  children,
}: {
  title: string
  /** Строка под заголовком (напр. «Показано X из Y»). */
  subtitle?: ReactNode
  /** Сводная информация из таблицы (справа от заголовка). */
  stats?: ReactNode
  /** Подсказка под сводкой (напр. про команду бота). */
  hint?: ReactNode
  /** Кнопка/действие справа от сводки; подсказка в этом случае идёт под кнопкой. */
  action?: ReactNode
  /** Не переводить заголовок в верхний регистр (брендованные названия). */
  noUppercase?: boolean
  /** Обычный шрифт вместо Orbitron (для длинных латинских названий). */
  plainTitle?: boolean
  /** Иконка/картинка рядом с заголовком. */
  titleAdornment?: ReactNode
  children?: ReactNode
}) {
  return (
    <div className="border-b bg-white/[0.03] px-6 py-4 [border-color:color-mix(in_srgb,var(--accent)_20%,transparent)]">
      <div className="flex flex-wrap items-start gap-x-4 gap-y-3">
        <div className="flex min-w-0 items-center gap-3">
          {titleAdornment}
          <div className="min-w-0">
            <h1
              className={cn(
                'text-lg tracking-wide text-[var(--text)]',
                plainTitle ? 'font-sans' : 'font-social uppercase',
                noUppercase && 'normal-case',
              )}
            >
              {title}
            </h1>
            {subtitle ? (
              <p className="mt-0.5 text-xs text-[var(--text-muted)]">{subtitle}</p>
            ) : null}
          </div>
        </div>
        {action ? (
          <div className="ml-0 flex min-w-0 flex-wrap items-start gap-x-4 gap-y-2 sm:ml-6">
            {stats ? (
              <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">
                {stats}
              </div>
            ) : null}
            <div className="flex min-w-0 flex-col gap-2">
              <div className="flex flex-wrap items-center gap-2">{action}</div>
              {hint ? <p className="text-xs text-[var(--text)]">{hint}</p> : null}
            </div>
          </div>
        ) : (
          <div className="ml-0 flex min-w-0 flex-col gap-2 sm:ml-6">
            {stats ? (
              <div className="flex flex-wrap items-center gap-2">{stats}</div>
            ) : null}
            {hint ? <p className="text-xs text-[var(--text)]">{hint}</p> : null}
          </div>
        )}
        <div className="ml-auto flex flex-wrap items-center justify-end gap-2">
          {children}
        </div>
      </div>
    </div>
  )
}
