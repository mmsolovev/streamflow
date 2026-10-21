import { Link } from 'react-router-dom'

export function NotFoundPage() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 p-8 text-center">
      <h1 className="font-social text-3xl text-[var(--text)]">404</h1>
      <p className="text-sm text-[var(--text-muted)]">Страница не найдена.</p>
      <Link
        to="/games"
        className="rounded-md border border-white/15 px-4 py-2 text-sm text-[var(--text)] transition-colors hover:bg-white/5"
      >
        На главную
      </Link>
    </div>
  )
}
