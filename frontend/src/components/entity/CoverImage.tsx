import { cn } from '@/lib/cn'

/**
 * Миниатюра обложки игры для ячеек таблиц.
 *
 * Без `fallback` скрывается при отсутствии картинки или ошибке загрузки. С
 * `fallback` вместо пустой обложки показывается заглушка, а при ошибке загрузки
 * источник подменяется на неё.
 */
export function CoverImage({
  src,
  alt = '',
  className,
  fallback,
}: {
  src: string | null | undefined
  alt?: string
  className?: string
  fallback?: string
}) {
  const source = src ?? fallback
  if (!source) return null
  return (
    <img
      src={source}
      alt={alt}
      loading="lazy"
      // Обложки в БД квадратные (90×90) — не растягиваем их в прямоугольник.
      className={cn('h-[45px] w-[45px] shrink-0 rounded-lg object-cover', className)}
      onError={(event) => {
        const img = event.currentTarget
        if (fallback && !img.dataset.fallback) {
          img.dataset.fallback = '1'
          img.src = fallback
        } else {
          img.style.display = 'none'
        }
      }}
    />
  )
}
