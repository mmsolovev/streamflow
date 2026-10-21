import type { ReactNode } from 'react'

import { SectionHeader } from '@/components/layout/SectionHeader'

/** Заготовка раздела: подшапка + сообщение «в разработке». */
export function PlaceholderPage({
  title,
  note,
  children,
}: {
  title: string
  note?: string
  children?: ReactNode
}) {
  return (
    <div className="flex flex-1 flex-col">
      <SectionHeader title={title} hint={note} />
      <div className="flex flex-1 items-center justify-center p-8 text-sm text-[var(--text-muted)]">
        {children ?? 'Раздел в разработке.'}
      </div>
    </div>
  )
}
