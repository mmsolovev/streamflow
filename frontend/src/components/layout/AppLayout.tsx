import { Link, Outlet } from 'react-router-dom'

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
      {/* На узких экранах боковой панели нет — ссылка уходит в подвал. */}
      <footer className="border-t border-white/10 px-4 py-3 md:hidden">
        <Link
          to="/privacy"
          className="text-xs text-[var(--text-muted)] transition-colors hover:text-[var(--text)]"
        >
          Политика конфиденциальности
        </Link>
      </footer>
      <ScrollToTop />
    </div>
  )
}
