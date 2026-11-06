import { useEffect, useRef, useState } from 'react'
import { ChevronDown } from 'lucide-react'
import { Link } from 'react-router-dom'

import { Button } from '@/components/ui/Button'
import { goToLogin } from '@/features/auth/api'
import { cn } from '@/lib/cn'

/**
 * Кнопка «Войти через Twitch» с выпадающим подтверждением согласия
 * с Политикой конфиденциальности.
 */
export function LoginMenu() {
  const [open, setOpen] = useState(false)
  const [agreed, setAgreed] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handlePointer = (event: MouseEvent) => {
      if (ref.current && !ref.current.contains(event.target as Node)) setOpen(false)
    }
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', handlePointer)
    document.addEventListener('keydown', handleKey)
    return () => {
      document.removeEventListener('mousedown', handlePointer)
      document.removeEventListener('keydown', handleKey)
    }
  }, [open])

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
        aria-haspopup="dialog"
        className="flex items-center gap-1 font-social text-sm tracking-wide text-[var(--accent)] transition-opacity hover:opacity-80"
      >
        Войти через Twitch
        <ChevronDown className={cn('h-4 w-4 transition-transform', open && 'rotate-180')} />
      </button>

      {open ? (
        <div
          role="dialog"
          aria-label="Вход через Twitch"
          className="absolute right-0 top-full z-50 mt-2 w-64 rounded-lg border border-white/10 bg-[var(--card-bg)] p-3 text-left shadow-xl shadow-black/40"
        >
          <Button
            variant="primary"
            className="w-full"
            disabled={!agreed}
            onClick={goToLogin}
          >
            Войти
          </Button>

          <label className="mt-3 flex cursor-pointer items-start gap-2 text-xs leading-snug text-[var(--text-muted)]">
            <input
              type="checkbox"
              checked={agreed}
              onChange={(event) => setAgreed(event.target.checked)}
              className="mt-0.5 h-3.5 w-3.5 shrink-0 accent-[var(--accent)]"
            />
            <span>
              Я согласен с{' '}
              <Link
                to="/privacy"
                target="_blank"
                rel="noreferrer"
                className="text-[var(--text)] underline decoration-white/30 underline-offset-2 transition-colors hover:decoration-white/70"
              >
                Политикой конфиденциальности
              </Link>
            </span>
          </label>
        </div>
      ) : null}
    </div>
  )
}
