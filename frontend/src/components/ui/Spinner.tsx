import { Loader2 } from 'lucide-react'

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-3 p-10 text-[var(--text-muted)]">
      <Loader2 className="h-6 w-6 animate-spin" />
      {label ? <span className="text-sm">{label}</span> : null}
    </div>
  )
}
