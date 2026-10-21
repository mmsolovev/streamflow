import { ChevronUp } from 'lucide-react'
import { useEffect, useState } from 'react'

/** Появляющаяся кнопка «Наверх» при прокрутке вниз. */
export function ScrollToTop() {
  const [visible, setVisible] = useState(false)

  useEffect(() => {
    const onScroll = () => {
      setVisible(window.scrollY > 320)
    }
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  if (!visible) return null

  return (
    <button
      type="button"
      onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
      title="Наверх"
      className="fixed bottom-6 right-6 z-40 rounded-full border border-white/10 bg-black/60 p-2 text-[var(--text)] shadow-lg backdrop-blur transition-colors hover:bg-white/10"
    >
      <ChevronUp className="h-5 w-5" />
    </button>
  )
}
