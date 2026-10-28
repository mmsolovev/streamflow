import { SectionBar } from '@/components/layout/SectionBar'
import { SectionPanel } from '@/components/layout/SectionPanel'
import type { BotSection } from '@/config/nav'
import { BotCommandsView } from '@/features/bot/BotCommandsView'
import type { ReactNode } from 'react'

const VIEWS: Record<BotSection, () => ReactNode> = {
  commands: BotCommandsView,
}

/** Группа «Бот»: панель разделов + представление раздела. */
export function BotPage({ section }: { section: BotSection }) {
  const View = VIEWS[section]

  return (
    // data-section включает палитру раздела для всех потомков.
    <div data-section={section} className="flex flex-1 flex-col bg-[var(--section-bg)]">
      {/* На узких экранах разделы — горизонтальной лентой над содержимым. */}
      <SectionBar />
      <div className="flex flex-1">
        <SectionPanel />
        <View />
      </div>
    </div>
  )
}
