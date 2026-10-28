import { useState } from 'react'
import type { FormEvent } from 'react'
import { X } from 'lucide-react'
import { toast } from 'sonner'

import { useAuth } from '@/features/auth/context'
import { goToLogin } from '@/features/auth/api'

interface AddBotCommandModalProps {
  open: boolean
  onClose: () => void
}

export function AddBotCommandModal({ open, onClose }: AddBotCommandModalProps) {
  const { isAuthenticated } = useAuth()
  const [botName, setBotName] = useState('')
  const [commandName, setCommandName] = useState('')
  const [description, setDescription] = useState('')
  const [isPending, setIsPending] = useState(false)

  if (!open) return null

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (!botName.trim() || !commandName.trim() || !description.trim()) {
      toast.error('Заполните все поля')
      return
    }
    setIsPending(true)
    setTimeout(() => {
      toast.success('Команда добавлена')
      setIsPending(false)
      onClose()
      setBotName('')
      setCommandName('')
      setDescription('')
    }, 300)
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div
        className="flex w-full max-w-lg flex-col overflow-hidden rounded-lg border shadow-xl shadow-black/40"
        style={{ background: '#24212E', borderColor: 'rgba(169, 112, 255, 0.4)' }}
      >
        <div
          className="flex shrink-0 items-center justify-between border-b px-5 py-3"
          style={{ borderColor: 'rgba(169, 112, 255, 0.3)' }}
        >
          <h2 className="font-social text-sm uppercase tracking-wide" style={{ color: '#A970FF' }}>
            Добавить команду другого бота
          </h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1.5 text-[var(--text-muted)] transition-colors hover:text-[var(--text)]"
            aria-label="Закрыть"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {!isAuthenticated ? (
          <div className="space-y-3 px-5 py-5">
            <p className="text-sm text-[var(--text)]">
              Чтобы добавить команду, нужно авторизоваться через Twitch.
            </p>
            <button
              type="button"
              onClick={goToLogin}
              className="rounded-md px-3 py-1.5 text-sm font-medium text-black transition-opacity hover:opacity-90"
              style={{ background: '#A970FF' }}
            >
              Войти через Twitch
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="flex flex-col">
            <div className="space-y-3 px-5 py-4">
              <div className="space-y-1">
                <label className="block text-xs uppercase tracking-wide text-[var(--text-muted)]">
                  Название бота
                </label>
                <input
                  value={botName}
                  onChange={(e) => setBotName(e.target.value)}
                  placeholder="StreamElements, Nightbot..."
                  className="w-full rounded-md border px-3 py-1.5 text-sm text-[var(--text)] outline-none transition-colors placeholder:text-[var(--text-muted)] focus:border-[#A970FF]"
                  style={{ background: '#18171F', borderColor: 'rgba(169, 112, 255, 0.3)' }}
                />
              </div>
              <div className="space-y-1">
                <label className="block text-xs uppercase tracking-wide text-[var(--text-muted)]">
                  Название команды
                </label>
                <input
                  value={commandName}
                  onChange={(e) => setCommandName(e.target.value)}
                  placeholder="!points"
                  className="w-full rounded-md border px-3 py-1.5 text-sm text-[var(--text)] outline-none transition-colors placeholder:text-[var(--text-muted)] focus:border-[#A970FF]"
                  style={{ background: '#18171F', borderColor: 'rgba(169, 112, 255, 0.3)' }}
                />
              </div>
              <div className="space-y-1">
                <label className="block text-xs uppercase tracking-wide text-[var(--text-muted)]">
                  Описание
                </label>
                <textarea
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  rows={3}
                  placeholder="Что делает команда"
                  className="w-full resize-none rounded-md border px-3 py-1.5 text-sm text-[var(--text)] outline-none transition-colors placeholder:text-[var(--text-muted)] focus:border-[#A970FF]"
                  style={{ background: '#18171F', borderColor: 'rgba(169, 112, 255, 0.3)' }}
                />
              </div>
            </div>
            <div
              className="flex items-center justify-end gap-2 border-t px-5 py-3"
              style={{ borderColor: 'rgba(169, 112, 255, 0.3)' }}
            >
              <button
                type="button"
                onClick={onClose}
                className="rounded-md border px-3 py-1.5 text-sm text-[var(--text)] transition-colors hover:bg-white/5"
                style={{ borderColor: 'rgba(169, 112, 255, 0.3)' }}
              >
                Отмена
              </button>
              <button
                type="submit"
                disabled={isPending}
                className="rounded-md px-3 py-1.5 text-sm font-medium text-black transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
                style={{ background: '#A970FF' }}
              >
                {isPending ? 'Сохранение...' : 'Добавить'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
