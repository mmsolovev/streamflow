import { useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { CheckCircle2, Search, User, X } from 'lucide-react'
import { toast } from 'sonner'
import { useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'

import {
  useAddRecommendation,
  useSearchRecommendationCandidates,
} from '@/features/recommendations/useRecommendations'
import { useAuth } from '@/features/auth/context'
import { goToLogin } from '@/features/auth/api'
import type { GameCandidate, UserSuggestion, UsersPage } from '@/api/types'
import { api } from '@/api/client'
import { cn } from '@/lib/cn'

interface RecommendGameModalProps {
  open: boolean
  onClose: () => void
}

type TargetList = 'releases' | 'recommendations'

interface SuccessInfo {
  title: string
  target: TargetList
  gameId: number | null
}

const TARGET_PATH: Record<TargetList, string> = {
  releases: '/releases',
  recommendations: '/recommendations',
}

async function searchUsers(query: string): Promise<UserSuggestion[]> {
  if (!query || query.trim().length < 2) return []
  const q = query.trim()
  const { data } = await api.get<UsersPage>('/users/search', { params: { q, limit: 10 } })
  return data.items ?? []
}

/** Модальное окно «Предложить игру» с поиском по IGDB и выбором кандидата. */
export function RecommendGameModal({ open, onClose }: RecommendGameModalProps) {
  const navigate = useNavigate()
  const location = useLocation()
  const [, setSearchParams] = useSearchParams()
  const { isAuthenticated, user, isAdmin } = useAuth()
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<GameCandidate | null>(null)
  const [note, setNote] = useState('')
  const [success, setSuccess] = useState<SuccessInfo | null>(null)
  const [activeField, setActiveField] = useState<'game' | 'user'>('game')

  // Введённый/выбранный никнейм (отображаемое имя) и его login для отправки.
  const [userText, setUserText] = useState<string | null>(null)
  const [userLoginOverride, setUserLoginOverride] = useState<string | null>(null)

  const canEditUser = isAuthenticated && isAdmin
  const ownLogin = user?.login ?? ''
  const ownDisplay = user?.display_name || ownLogin
  const userQuery = userText ?? ownDisplay

  const debounced = query.trim()
  const { data, isLoading } = useSearchRecommendationCandidates(debounced)
  const candidates = data?.candidates ?? []

  const { data: userCandidates = [], isLoading: isUsersLoading } = useQuery({
    queryKey: ['users', 'search', userQuery.trim()],
    queryFn: () => searchUsers(userQuery),
    enabled: canEditUser && userQuery.trim().length >= 2,
    staleTime: 30_000,
  })

  const mutation = useAddRecommendation()

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])

  // Логин, который уйдёт на сервер: выбранный из подсказок, введённый вручную
  // или собственный логин администратора.
  const targetLogin = useMemo(() => {
    if (!isAuthenticated || !canEditUser) return undefined
    return userLoginOverride || (userText !== null ? userText.trim() : '') || ownLogin
  }, [canEditUser, isAuthenticated, ownLogin, userLoginOverride, userText])

  if (!open) return null

  /** Подсвечивает добавленную игру в списке, если он открыт сейчас. */
  function focusGame(gameId: number | null) {
    if (gameId === null) return
    setSearchParams(
      (prev) => {
        const next = new URLSearchParams(prev)
        next.set('focus', String(gameId))
        return next
      },
      { replace: true },
    )
  }

  function goToTarget(target: TargetList, gameId: number | null) {
    onClose()
    const path = TARGET_PATH[target]
    if (location.pathname === path) {
      // Мы уже на нужной странице: обновляем список и пролистываем к игре.
      focusGame(gameId)
      return
    }
    navigate(gameId === null ? path : `${path}?focus=${gameId}`)
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    const q = query.trim()
    if (!q || mutation.isPending) return
    mutation.mutate(
      {
        query: q,
        igdbId: selected?.igdb_id,
        note: note.trim() || undefined,
        userLogin: targetLogin,
      },
      {
        onSuccess: (result) => {
          const target: TargetList =
            result.target_list === 'releases' ? 'releases' : 'recommendations'
          const gameId = result.recommendation?.id ?? null
          setSuccess({ title: result.recommendation?.title ?? q, target, gameId })
          // Если игра попала в открытый сейчас список — сразу показываем её.
          if (location.pathname === TARGET_PATH[target]) {
            focusGame(gameId)
          }
        },
        onError: (error) => {
          toast.error(error.message)
        },
      },
    )
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="flex h-[560px] max-h-[calc(100dvh-3rem)] w-full max-w-2xl flex-col overflow-hidden rounded-lg border border-white/10 bg-[var(--card-bg)] shadow-xl shadow-black/40">
        <div className="flex shrink-0 items-center justify-between border-b border-white/10 px-5 py-3">
          <h2 className="font-social text-sm uppercase tracking-wide text-[var(--text)]">
            Предложить игру
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

        {success ? (
          <div className="flex flex-1 flex-col justify-center gap-5 px-5 py-6">
            <div className="flex items-start gap-3">
              <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-[var(--accent)]" />
              <p className="text-sm text-[var(--text)]">
                Игра «{success.title}» добавлена в{' '}
                <span className="font-semibold text-[var(--accent)]">
                  {success.target === 'releases' ? 'Релизы' : 'Советы'}
                </span>
                .
              </p>
            </div>
            <div className="flex flex-wrap items-center justify-end gap-2">
              <button
                type="button"
                onClick={onClose}
                className="rounded-md border border-white/15 px-3 py-1.5 text-sm text-[var(--text)] transition-colors hover:bg-white/5"
              >
                ОК
              </button>
              <button
                type="button"
                onClick={() => goToTarget(success.target, success.gameId)}
                className="rounded-md bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-black transition-opacity hover:opacity-90"
              >
                {success.target === 'releases' ? 'Релизы' : 'Советы'}
              </button>
            </div>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="flex min-h-0 flex-1 flex-col">
            {!isAuthenticated ? (
              <div className="space-y-3 px-5 py-5">
                <p className="text-sm text-[var(--text)]">
                  Чтобы предложить игру, нужно войти через Twitch.
                </p>
                <button
                  type="button"
                  onClick={goToLogin}
                  className="rounded-md bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-black transition-opacity hover:opacity-90"
                >
                  Войти через Twitch
                </button>
              </div>
            ) : (
              <>
                <div className="space-y-3 px-5 py-4">
                  <div className="space-y-1">
                    <label className="block text-xs uppercase tracking-wide text-[var(--text-muted)]">
                      Пользователь
                    </label>
                    <div className="relative">
                      <User className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--text-muted)]" />
                      <input
                        value={userQuery}
                        onChange={(e) => {
                          setUserText(e.target.value)
                          setUserLoginOverride(null)
                        }}
                        onFocus={() => setActiveField('user')}
                        readOnly={!canEditUser}
                        placeholder="Никнейм пользователя"
                        className="w-full rounded-md border border-white/15 bg-[var(--card-bg)] py-1.5 pl-9 pr-3 text-sm text-[var(--text)] outline-none transition-colors placeholder:text-[var(--text-muted)] focus:border-[var(--accent)] disabled:opacity-60"
                      />
                    </div>
                  </div>

                  <div className="flex items-center gap-2">
                    <div className="relative flex-1">
                      <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--text-muted)]" />
                      <input
                        value={query}
                        onChange={(e) => {
                          setQuery(e.target.value)
                          setSelected(null)
                        }}
                        onFocus={() => setActiveField('game')}
                        placeholder="Название игры…"
                        className="w-full rounded-md border border-white/15 bg-[var(--card-bg)] py-1.5 pl-9 pr-3 text-sm text-[var(--text)] outline-none transition-colors placeholder:text-[var(--text-muted)] focus:border-[var(--accent)]"
                      />
                    </div>
                    <button
                      type="submit"
                      disabled={mutation.isPending || debounced.length === 0}
                      className="rounded-md bg-[var(--accent)] px-3 py-1.5 text-sm font-medium text-black transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      {mutation.isPending ? 'Отправка…' : 'Предложить'}
                    </button>
                  </div>

                  <div>
                    <label
                      htmlFor="recommend-note"
                      className="mb-1 block text-xs uppercase tracking-wide text-[var(--text-muted)]"
                    >
                      Комментарий (по желанию)
                    </label>
                    <textarea
                      id="recommend-note"
                      value={note}
                      onChange={(e) => setNote(e.target.value)}
                      rows={2}
                      maxLength={500}
                      placeholder="Почему стоит посмотреть?"
                      className="w-full resize-none rounded-md border border-white/15 bg-[var(--card-bg)] px-3 py-1.5 text-sm text-[var(--text)] outline-none transition-colors placeholder:text-[var(--text-muted)] focus:border-[var(--accent)]"
                    />
                  </div>
                </div>

                <div className="min-h-0 flex-1 overflow-y-auto border-t border-white/10 px-5 py-2">
                  {activeField === 'user' ? (
                    !canEditUser ? (
                      <p className="py-2 text-xs text-[var(--text-muted)]">
                        Выбирать пользователя может только администратор.
                      </p>
                    ) : userQuery.trim().length < 2 ? (
                      <p className="py-2 text-xs text-[var(--text-muted)]">
                        Введите минимум 2 символа, чтобы найти никнейм.
                      </p>
                    ) : isUsersLoading ? (
                      <p className="py-2 text-xs text-[var(--text-muted)]">
                        Поиск никнеймов…
                      </p>
                    ) : userCandidates.length === 0 ? (
                      <p className="py-2 text-xs text-[var(--text-muted)]">
                        Никнеймы не найдены.
                      </p>
                    ) : (
                      <div className="space-y-1 py-1">
                        {userCandidates.map((c) => (
                          <button
                            type="button"
                            key={c.login}
                            onClick={() => {
                              setUserText(c.display_name || c.login || '')
                              setUserLoginOverride(c.login ?? null)
                            }}
                            className="w-full rounded-md px-2 py-1.5 text-left text-sm font-medium text-[var(--text)] hover:bg-white/5"
                          >
                            {c.display_name || c.login}
                          </button>
                        ))}
                      </div>
                    )
                  ) : debounced.length < 2 ? (
                    <p className="py-2 text-xs text-[var(--text-muted)]">
                      Введите название игры, чтобы увидеть варианты.
                    </p>
                  ) : isLoading ? (
                    <p className="py-2 text-xs text-[var(--text-muted)]">
                      Поиск вариантов…
                    </p>
                  ) : candidates.length === 0 ? (
                    <p className="py-2 text-xs text-[var(--text-muted)]">
                      Ничего не найдено.
                    </p>
                  ) : (
                    <div className="space-y-1.5 py-1">
                      {candidates.map((c) => {
                        const isSel = selected?.igdb_id === c.igdb_id
                        return (
                          <button
                            type="button"
                            key={c.igdb_id}
                            onClick={() => {
                              setSelected(isSel ? null : c)
                              if (!isSel) setQuery(c.title)
                            }}
                            className={cn(
                              'w-full rounded-md border px-3 py-2 text-left transition-colors',
                              isSel
                                ? 'border-[var(--accent)] bg-[color-mix(in_srgb,var(--accent)_15%,transparent)]'
                                : 'border-white/10 hover:bg-white/5',
                            )}
                          >
                            <div className="flex items-baseline justify-between gap-2">
                              <div className="min-w-0 text-sm font-medium text-[var(--text)]">
                                {c.title}
                              </div>
                              {c.release_year ? (
                                <span className="shrink-0 text-xs text-[var(--text-muted)]">
                                  {c.release_year}
                                </span>
                              ) : null}
                            </div>
                            {(c.platforms || c.genres) && (
                              <div className="mt-1 truncate text-xs text-[var(--text-muted)]">
                                {[c.platforms, c.genres].filter(Boolean).join(' • ')}
                              </div>
                            )}
                          </button>
                        )
                      })}
                    </div>
                  )}
                </div>
              </>
            )}
          </form>
        )}
      </div>
    </div>
  )
}
