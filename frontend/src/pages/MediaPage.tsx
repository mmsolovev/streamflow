import { SectionBar } from '@/components/layout/SectionBar'
import { SectionPanel } from '@/components/layout/SectionPanel'
import type { MediaSection } from '@/config/nav'
import { MediaView } from '@/features/media/MediaView'

/** Раздел «Медиа»: записи VOD и клипы в виде крупных карточек. */
export function MediaPage({ section }: { section: MediaSection }) {
  return (
    <div data-section={section} className="flex flex-1 flex-col bg-[var(--section-bg)]">
      <SectionBar />
      <div className="flex flex-1">
        <SectionPanel />
        <MediaView key={section} section={section} />
      </div>
    </div>
  )
}
