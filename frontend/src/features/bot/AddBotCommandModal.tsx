import { useState } from 'react'
import type { FormEvent } from 'react'
import { X } from 'lucide-react'
import { toast } from 'sonner'

import { useAuth } from '@/features/auth/context'
import { useCreateBotCommand } from '@/features/bot/useBotCommands'

interface AddBotCommandModalProps {
  open: boolean
  onClose: () => void
}

export function AddBotCommandModal({ open, onClose }: AddBotCommandModalProps) {
  const { isAdmin } = useAuth()
  const createCommand = useCreateBotCommand()
  const [botName, setBotName] = useState('')
  const [commandName, setCommandName] = useState('')
  const [description, setDescription] = useState('')

  if (!open) return null

  async function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (!commandName.trim() || !description.trim()) {
      toast.error('Заполните название команды и описание')
      return
    }

    try {
      await createCommand.mutateAsync({
        name: commandName.trim(),
        description: description.trim(),
        bot_name: botName.trim() || 'self',
      })
      setBotName('')
      setCommandName('')
      setDescription('')
      onClose()
    } catch {
      // Ошибка уже показана в onError хука.
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="flex w-full max-w-lg flex-col overflow-hidden rounded-lg border border-[var(--accent)] bg-[var(--card-bg)] shadow-xl shadow-black/40">
        <div className="flex shrink-0 items-center justify-between border-b border-[color-mix(in_srgb,var(--accent)_30%,transparent)] px-5 py-3">
          <h2 className="font-social text-sm uppercase tracking-wide text-[var(--accent)]">
            Добавить команду
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

        {!isAdmin ? (
          <div className="px-5 py-5">
            <p className="text-sm text-[var(--text)]">
              Добавлять команды могут только администраторы.
            </p>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="flex flex-col">
            <div className="space-y-3 px-5 py-4">
              <div className="space-y-1">
                <label className="block text-xs uppercase tracking-wide text-[var(--text-muted)]">
                  Название команды
                </label>
                <input
                  value={commandName}
                  onChange={(e) => setCommandName(e.target.value)}
                  placeholder="!points"
                  className="w-full rounded-md border border-[color-mix(in_srgb,var(--accent)_30%,transparent)] bg-[var(--section-bg)] px-3 py-1.5 text-sm text-[var(--text)] outline-none transition-colors placeholder:text-[var(--text-muted)] focus:border-[var(--accent)]"
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
                  className="w-full resize-none rounded-md border border-[color-mix(in_srgb,var(--accent)_30%,transparent)] bg-[var(--section-bg)] px-3 py-1.5 text-sm text-[var(--text)] outline-none transition-colors placeholder:text-[var(--text-muted)] focus:border-[var(--accent)]"
                />
              </div>
              <div className="space-y-1">
                <label className="block text-xs uppercase tracking-wide text-[var(--text-muted)]">
                  Бот
                </label>
                <input
                  value={botName}
                  onChange={(e) => setBotName(e.target.value)}
                  placeholder="StreamElements, Nightbot... (пусто — mishgan_sol)"
                  className="w-full rounded-md border border-[color-mix(in_srgb,var(--accent)_30%,transparent)] bg-[var(--section-bg)] px-3 py-1.5 text-sm text-[var(--text)] outline-none transition-colors placeholder:text-[var(--text-muted)] focus:border-[var(--accent)]"
                />
              </div>
            </div>
            <div className="flex items-center justify-end gap-2 border-t border-[color-mix(in_srgb,var(--accent)_30%,transparent)] px-5 py-3">
              <button
                type="button"
                onClick={onClose}
                className="rounded-md border border-[color-mix(in_srgb,var(--accent)_30%,transparent)] px-3 py-1.5 text-sm text-[var(--text)] transition-colors hover:bg-white/5"
              >
                Отмена
              </button>
              <button
                type="submit"
                disabled={createCommand.isPending}
                className="rounded-md bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-black transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {createCommand.isPending ? 'Сохранение...' : 'Добавить'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}
