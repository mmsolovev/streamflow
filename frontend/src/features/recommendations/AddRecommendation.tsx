import { useState } from 'react'
import { Plus } from 'lucide-react'

import { useAuth } from '@/features/auth/context'
import { RecommendGameModal } from '@/features/recommendations/RecommendGameModal'
import { cn } from '@/lib/cn'

/** Кнопка «Предложить игру» (открывает модальное окно с поиском IGDB). */
export function AddRecommendation() {
  const { isAuthenticated } = useAuth()
  const [open, setOpen] = useState(false)

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={cn(
          'flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm transition-colors',
          isAuthenticated
            ? 'bg-[var(--accent)] font-medium text-black hover:opacity-90'
            : 'border border-[var(--accent)] text-[var(--accent)] hover:opacity-80',
        )}
      >
        <Plus className="h-4 w-4" />
        Предложить игру
      </button>
      {open ? <RecommendGameModal open onClose={() => setOpen(false)} /> : null}
    </>
  )
}
