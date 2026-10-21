import { Skeleton } from '@/components/ui/Skeleton'

/**
 * Скелетон страницы игры: повторяет три столбца (общая информация, стримы,
 * время прохождения), чтобы при загрузке не мигала пустотой.
 */
export function GameDetailSkeleton() {
  return (
    <div className="grid grid-cols-1 gap-6 p-6 lg:grid-cols-3">
      {/* Первый столбик — общая информация. */}
      <div className="flex flex-col bg-[var(--card-bg)] px-4 py-4">
        <div className="mb-4 flex items-center gap-3">
          <Skeleton className="h-[45px] w-[45px] shrink-0 rounded-lg" />
          <Skeleton className="h-6 w-2/3" />
        </div>
        <Skeleton className="mb-3 h-4 w-full" />
        <Skeleton className="mb-3 h-4 w-5/6" />
        <Skeleton className="mb-4 h-4 w-4/6" />
        {Array.from({ length: 6 }).map((_, index) => (
          <div
            key={index}
            className="flex items-baseline justify-between gap-4 border-b border-white/5 py-2"
          >
            <Skeleton className="h-3 w-20" />
            <Skeleton className="h-3 w-1/3" />
          </div>
        ))}
      </div>

      {/* Второй столбик — стримы. */}
      <div className="flex flex-col bg-[var(--card-bg)] px-4 py-4">
        <Skeleton className="mb-2 h-3 w-28" />
        {Array.from({ length: 5 }).map((_, index) => (
          <div
            key={index}
            className="flex items-baseline justify-between gap-3 border-b border-white/5 py-2"
          >
            <Skeleton className="h-3 w-2/3" />
            <Skeleton className="h-3 w-10" />
          </div>
        ))}
      </div>

      {/* Третий столбик — время прохождения и рекомендации. */}
      <div className="flex flex-col bg-[var(--card-bg)] px-4 py-4">
        <Skeleton className="mb-2 h-3 w-32" />
        {Array.from({ length: 5 }).map((_, index) => (
          <div
            key={index}
            className="flex items-baseline justify-between gap-4 border-b border-white/5 py-2"
          >
            <Skeleton className="h-3 w-24" />
            <Skeleton className="h-3 w-16" />
          </div>
        ))}
      </div>
    </div>
  )
}
