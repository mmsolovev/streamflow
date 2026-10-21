import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Link2, Search, X } from 'lucide-react'

import { useAddHltb, useHltbLookup } from '@/features/hltb/useHltb'
import { formatHltbTime } from '@/lib/format'

interface AddHltbModalProps {
  open: boolean
  onClose: () => void
}

/** Окно «Добавить игру»: ссылка на HowLongToBeat → поиск → подтверждение. */
export function AddHltbModal({ open, onClose }: AddHltbModalProps) {
  const [url, setUrl] = useState('')
  const lookup = useHltbLookup()
  const add = useAddHltb()

  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  const found = lookup.data

  function handleLookup(event: FormEvent) {
    event.preventDefault()
    const value = url.trim()
    if (!value || lookup.isPending) return
    lookup.mutate(value)
  }

  function handleAdd() {
    if (!found || add.isPending) return
    add.mutate(
      { url: url.trim(), gameId: found.game_id },
      {
        onSuccess: () => {
          setUrl('')
          lookup.reset()
          onClose()
        },
      },
    )
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4"
      onClick={onClose}
    >
      <div
        onClick={(event) => event.stopPropagation()}
        className="w-full max-w-lg overflow-hidden rounded-lg border border-white/10 bg-[var(--card-bg)] shadow-xl shadow-black/40"
      >
        <div className="flex items-center justify-between border-b border-white/10 px-5 py-3">
          <h2 className="font-social text-sm uppercase tracking-wide text-[var(--text)]">
            Добавить игру
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

        <form onSubmit={handleLookup} className="space-y-4 px-5 py-4">
          <div className="space-y-1">
            <label
              htmlFor="hltb-url"
              className="block text-xs uppercase tracking-wide text-[var(--text-muted)]"
            >
              Ссылка на HowLongToBeat
            </label>
            <div className="relative">
              <Link2 className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--text-muted)]" />
              <input
                id="hltb-url"
                value={url}
                onChange={(event) => {
                  setUrl(event.target.value)
                  lookup.reset()
                }}
                placeholder="https://howlongtobeat.com/game/84121"
                className="w-full rounded-md border border-white/15 bg-[var(--section-bg)] py-1.5 pl-9 pr-3 text-sm text-[var(--text)] outline-none transition-colors placeholder:text-[var(--text-muted)] focus:border-[var(--accent)]"
              />
            </div>
          </div>

          <div className="flex justify-end">
            <button
              type="submit"
              disabled={url.trim().length === 0 || lookup.isPending}
              className="inline-flex items-center gap-1.5 rounded-md border border-white/15 px-3 py-1.5 text-sm text-[var(--text)] transition-colors hover:bg-white/5 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <Search className="h-4 w-4" />
              {lookup.isPending ? 'Ищем…' : 'Найти'}
            </button>
          </div>

          {lookup.isError ? (
            <p className="text-sm text-red-400">{lookup.error.message}</p>
          ) : null}

          {found ? (
            <div className="space-y-3 rounded-md border border-white/10 bg-[var(--section-bg)] px-4 py-3">
              <div className="text-sm text-[var(--text)]">
                <span className="font-semibold">{found.hltb_name || 'Без названия'}</span>
                <span className="ml-2 text-xs text-[var(--text-muted)]">
                  id {found.hltb_id}
                </span>
              </div>

              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-[var(--text-muted)]">
                <div>Все стили: {formatHltbTime(found.all_styles)}</div>
                <div>Сюжет: {formatHltbTime(found.main_story)}</div>
                <div>Сюжет+Доп: {formatHltbTime(found.main_extra)}</div>
                <div>Полное: {formatHltbTime(found.completionist)}</div>
                <div>Кооп: {formatHltbTime(found.coop)}</div>
                <div>Мультиплеер: {formatHltbTime(found.multiplayer)}</div>
              </div>

              <div className="border-t border-white/10 pt-2 text-xs text-[var(--text-muted)]">
                {found.already_added ? (
                  <>
                    Игра уже есть в базе:{' '}
                    <span className="text-[var(--text)]">{found.game_name}</span>. Данные
                    будут обновлены.
                  </>
                ) : (
                  <>
                    В базе такой игры нет — она будет создана:{' '}
                    <span className="text-[var(--text)]">{found.game_name}</span>.
                    Информация из IGDB обновится автоматически.
                  </>
                )}
              </div>

              <div className="flex justify-end gap-2 pt-1">
                <button
                  type="button"
                  onClick={onClose}
                  className="rounded-md border border-white/15 px-3 py-1.5 text-sm text-[var(--text)] transition-colors hover:bg-white/5"
                >
                  Отмена
                </button>
                <button
                  type="button"
                  onClick={handleAdd}
                  disabled={add.isPending}
                  className="rounded-md bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-black transition-opacity enabled:hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  {add.isPending ? 'Добавляем…' : 'Добавить'}
                </button>
              </div>
            </div>
          ) : null}
        </form>
      </div>
    </div>
  )
}
