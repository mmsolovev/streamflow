import { Outlet } from 'react-router-dom'

import { TopBar } from '@/components/layout/TopBar'

import { ScrollToTop } from '@/components/ui/ScrollToTop'

/** Общий каркас: верхняя полоса + содержимое страницы. */
export function AppLayout() {
  return (
    <div className="flex min-h-screen flex-col bg-[var(--page-bg)]">
      <TopBar />
      <main className="flex flex-1 flex-col">
        <Outlet />
      </main>
      <ScrollToTop />
    </div>
  )
}
