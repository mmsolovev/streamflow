import { SectionBar } from '@/components/layout/SectionBar'
import { SectionPanel } from '@/components/layout/SectionPanel'
import type { StatsSection } from '@/config/nav'
import { GamesView } from '@/features/games/GamesView'
import { HltbTable } from '@/features/hltb/HltbTable'
import { RecommendationsView } from '@/features/recommendations/RecommendationsView'
import { ReleasesView } from '@/features/releases/ReleasesView'
import { StreamsView } from '@/features/streams/StreamsView'
import type { ReactNode } from 'react'

const VIEWS: Record<StatsSection, () => ReactNode> = {
  games: GamesView,
  streams: StreamsView,
  releases: ReleasesView,
  recommendations: RecommendationsView,
  hltb: HltbTable,
}

/** Группа «Статистика»: панель разделов + представление раздела. */
export function StatsPage({ section }: { section: StatsSection }) {
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
