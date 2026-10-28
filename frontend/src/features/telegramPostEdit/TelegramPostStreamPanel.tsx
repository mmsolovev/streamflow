import { useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  RotateCcw,
  Save,
  Send,
  Undo2,
} from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/Button'
import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { Skeleton } from '@/components/ui/Skeleton'
import { cn } from '@/lib/cn'
import { formatDateTime } from '@/lib/format'
import {
  checkVod,
  getPostStream,
  publishNow,
  resetSettings,
  restoreOriginal,
  selectTarget,
  undoEdit,
  updateSettings,
} from './api'
import type { PostEditRun, PostEditSettings, VodCheckResult } from './types'

interface Draft {
  enabled: boolean
  delay_minutes: string
  header: string
  item: string
  separator: string
  footer: string
  link_label: string
}

const STATUS_LABELS: Record<string, string> = {
  pending_selection: 'Нужен пост',
  waiting: 'Ждёт VOD',
  resolved: 'VOD найден',
  no_vod: 'Нет VOD',
  ready: 'Готово к правке',
  applying: 'Правится',
  edited: 'Отредактирован',
  edit_failed: 'Ошибка правки',
  failed: 'Ошибка проверки',
  undone: 'Правка отменена',
}

const STATUS_TONE: Record<string, string> = {
  pending_selection: 'text-amber-300 bg-amber-400/10',
  waiting: 'text-sky-300 bg-sky-400/10',
  resolved: 'text-sky-300 bg-sky-400/10',
  no_vod: 'text-amber-300 bg-amber-400/10',
  ready: 'text-sky-300 bg-sky-400/10',
  applying: 'text-sky-300 bg-sky-400/10',
  edited: 'text-emerald-300 bg-emerald-400/10',
  edit_failed: 'text-red-300 bg-red-400/10',
  failed: 'text-red-300 bg-red-400/10',
  undone: 'text-[var(--text-muted)] bg-white/5',
}

function toDraft(settings: PostEditSettings): Draft {
  return {
    enabled: settings.enabled,
    delay_minutes: String(Math.round(settings.delay_seconds / 6) / 10),
    header: settings.header,
    item: settings.item,
    separator: settings.separator,
    footer: settings.footer,
    link_label: settings.link_label,
  }
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : 'Не удалось выполнить действие.'
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span
      className={cn(
        'rounded px-1.5 py-0.5 text-[11px] uppercase tracking-wide',
        STATUS_TONE[status] ?? 'text-[var(--text-muted)] bg-white/5',
      )}
    >
      {STATUS_LABELS[status] ?? status}
    </span>
  )
}

function Field({
  label,
  hint,
  children,
}: {
  label: string
  hint?: string
  children: ReactNode
}) {
  return (
    <label className="block">
      <span className="mb-1 flex items-baseline justify-between gap-2 text-xs uppercase tracking-wide text-[var(--text-muted)]">
        {label}
        {hint ? (
          <span className="normal-case tracking-normal opacity-70">{hint}</span>
        ) : null}
      </span>
      {children}
    </label>
  )
}

const inputClass =
  'w-full rounded-md border border-white/10 bg-black/20 px-2.5 py-1.5 text-sm text-[var(--text)] outline-none transition-colors focus:border-[var(--accent)]'

function RunRow({
  run,
  active,
  onSelect,
}: {
  run: PostEditRun
  active: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        'w-full border-b border-white/5 px-4 py-3 text-left transition-colors',
        active ? 'bg-[var(--accent)]/10' : 'hover:bg-white/5',
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-sm text-[var(--text)]">
          {run.stream_title || `Стрим ${run.stream_id}`}
        </span>
        <StatusBadge status={run.status} />
      </div>
      <div className="mt-1 flex items-center gap-2 text-xs text-[var(--text-muted)]">
        <Clock3 className="h-3.5 w-3.5" />
        {formatDateTime(run.stream_ended_at || run.stream_started_at)}
      </div>
    </button>
  )
}

export function TelegramPostStreamPanel() {
  const queryClient = useQueryClient()
  const [runId, setRunId] = useState<number | null>(null)
  const [draftState, setDraftState] = useState<{ key: string; draft: Draft } | null>(null)
  const [checkState, setCheckState] = useState<{
    runId: number | null
    result: VodCheckResult
  } | null>(null)
  const [confirmAction, setConfirmAction] = useState<
    'reset' | 'publish' | 'undo' | 'restore' | null
  >(null)

  const query = useQuery({
    queryKey: ['telegram-post-edit', runId],
    queryFn: () => getPostStream(runId),
    refetchInterval: (current) => {
      const status = current.state.data?.target?.status
      return status === 'applying' || status === 'waiting' ? 5000 : false
    },
  })

  const settings = query.data?.settings
  const target = query.data?.target
  const settingsKey = settings ? JSON.stringify(settings) : ''
  const draft =
    settings && draftState?.key === settingsKey
      ? draftState.draft
      : settings
        ? toDraft(settings)
        : null
  const setDraft = (next: Draft) => setDraftState({ key: settingsKey, draft: next })
  const checkResult =
    checkState && target && checkState.runId === target.id ? checkState.result : null

  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: ['telegram-post-edit'] })

  const saveMutation = useMutation({
    mutationFn: () => {
      if (!draft) throw new Error('Форма не загружена.')
      const minutes = Number(draft.delay_minutes.replace(',', '.'))
      if (!Number.isFinite(minutes) || minutes < 0) {
        throw new Error('Некорректная задержка.')
      }
      return updateSettings({
        enabled: draft.enabled,
        delay_seconds: Math.round(minutes * 60),
        header: draft.header,
        item: draft.item,
        separator: draft.separator,
        footer: draft.footer,
        link_label: draft.link_label,
      })
    },
    onSuccess: () => {
      toast.success('Настройки сохранены.')
      void refresh()
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  const resetMutation = useMutation({
    mutationFn: resetSettings,
    onSuccess: () => {
      toast.success('Шаблон сброшен к значениям по умолчанию.')
      setConfirmAction(null)
      void refresh()
    },
    onError: (error) => {
      setConfirmAction(null)
      toast.error(errorMessage(error))
    },
  })

  const targetMutation = useMutation({
    mutationFn: (announcementId: number) => {
      if (!query.data?.target) throw new Error('Стрим не выбран.')
      return selectTarget(query.data.target.id, announcementId)
    },
    onSuccess: (result) => {
      toast.success(result.message)
      void refresh()
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  const checkMutation = useMutation({
    mutationFn: async () => {
      const id = query.data?.target?.id
      if (!id) throw new Error('Стрим не выбран.')
      return { runId: id, result: await checkVod(id) }
    },
    onSuccess: ({ runId: checkedRunId, result }) => {
      setCheckState({ runId: checkedRunId, result })
      if (result.available) {
        toast.success('VOD доступен.')
      } else {
        toast.error(result.error || 'VOD не найден.')
      }
      void refresh()
    },
    onError: (error) => toast.error(errorMessage(error)),
  })

  const publishMutation = useMutation({
    mutationFn: () => {
      if (!query.data?.target) throw new Error('Стрим не выбран.')
      return publishNow(query.data.target.id)
    },
    onSuccess: (result) => {
      toast.success(result.message)
      setConfirmAction(null)
      void refresh()
    },
    onError: (error) => {
      setConfirmAction(null)
      toast.error(errorMessage(error))
    },
  })

  const undoMutation = useMutation({
    mutationFn: () => {
      if (!query.data?.target) throw new Error('Стрим не выбран.')
      return undoEdit(query.data.target.id)
    },
    onSuccess: (result) => {
      toast.success(result.message)
      setConfirmAction(null)
      void refresh()
    },
    onError: (error) => {
      setConfirmAction(null)
      toast.error(errorMessage(error))
    },
  })

  const restoreMutation = useMutation({
    mutationFn: () => {
      if (!query.data?.target) throw new Error('Стрим не выбран.')
      return restoreOriginal(query.data.target.id)
    },
    onSuccess: (result) => {
      toast.success(result.message)
      setConfirmAction(null)
      void refresh()
    },
    onError: (error) => {
      setConfirmAction(null)
      toast.error(errorMessage(error))
    },
  })

  if (query.isLoading) {
    return (
      <div className="grid gap-4 p-6 lg:grid-cols-[320px_1fr_1fr]">
        {Array.from({ length: 3 }).map((_, index) => (
          <Skeleton key={index} className="h-80" />
        ))}
      </div>
    )
  }
  if (query.isError) {
    return <ErrorState error={query.error} onRetry={() => void query.refetch()} />
  }

  const data = query.data
  if (!data) return null

  const busy =
    saveMutation.isPending ||
    resetMutation.isPending ||
    targetMutation.isPending ||
    publishMutation.isPending ||
    undoMutation.isPending ||
    restoreMutation.isPending
  const canPublish =
    Boolean(target?.announcement_id) &&
    target?.status !== 'applying' &&
    target?.status !== 'edited'
  const canUndo = target?.status === 'edited'
  const canRestore = target?.status === 'edited'

  return (
    <div className="grid min-h-0 flex-1 gap-4 p-4 xl:grid-cols-3">
      <section className="flex min-h-0 flex-col overflow-hidden border border-white/10 bg-[var(--card-bg)]">
        <header className="border-b border-white/10 px-4 py-3">
          <h2 className="font-social text-sm uppercase tracking-wide">
            Настройки правки
          </h2>
        </header>

        {draft ? (
          <div className="flex min-h-0 flex-1 flex-col">
            <div className="space-y-4 overflow-y-auto px-4 py-4">
              <div className="flex items-center justify-between gap-3 rounded-md border border-white/10 px-3 py-2">
                <div>
                  <div className="text-sm">Автоматическая правка</div>
                  <div className="text-xs text-[var(--text-muted)]">
                    Отключение не мешает выбирать пост и публиковать вручную.
                  </div>
                </div>
                <button
                  type="button"
                  aria-label="Автоматическая правка"
                  aria-pressed={draft.enabled}
                  onClick={() => setDraft({ ...draft, enabled: !draft.enabled })}
                  className={cn(
                    'relative h-6 w-11 shrink-0 rounded-full transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]',
                    draft.enabled ? 'bg-[var(--accent)]' : 'bg-white/15',
                  )}
                >
                  <span
                    className={cn(
                      'absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white transition-transform',
                      draft.enabled ? 'translate-x-5' : 'translate-x-0.5',
                    )}
                  />
                </button>
              </div>

              <Field label="Задержка" hint="минут после конца стрима">
                <input
                  type="number"
                  min={0}
                  step={0.5}
                  value={draft.delay_minutes}
                  onChange={(event) =>
                    setDraft({ ...draft, delay_minutes: event.target.value })
                  }
                  className={inputClass}
                />
              </Field>

              <Field label="Заголовок" hint="один раз">
                <textarea
                  rows={2}
                  value={draft.header}
                  onChange={(event) => setDraft({ ...draft, header: event.target.value })}
                  className={cn(inputClass, 'resize-y font-mono')}
                />
              </Field>

              <Field label="Запись" hint="{{link}} обязателен">
                <textarea
                  rows={3}
                  value={draft.item}
                  onChange={(event) => setDraft({ ...draft, item: event.target.value })}
                  className={cn(inputClass, 'resize-y font-mono')}
                />
              </Field>

              <Field label="Разделитель" hint="между записями">
                <textarea
                  rows={2}
                  value={draft.separator}
                  onChange={(event) =>
                    setDraft({ ...draft, separator: event.target.value })
                  }
                  className={cn(inputClass, 'resize-y font-mono')}
                />
              </Field>

              <Field label="Подвал" hint="после всех записей">
                <textarea
                  rows={2}
                  value={draft.footer}
                  onChange={(event) => setDraft({ ...draft, footer: event.target.value })}
                  className={cn(inputClass, 'resize-y font-mono')}
                />
              </Field>

              <Field label="Текст ссылки" hint="виден в Telegram">
                <input
                  value={draft.link_label}
                  onChange={(event) =>
                    setDraft({ ...draft, link_label: event.target.value })
                  }
                  className={inputClass}
                />
              </Field>
            </div>

            <div className="flex items-center gap-2 border-t border-white/10 px-4 py-3">
              <Button
                variant="primary"
                onClick={() => saveMutation.mutate()}
                disabled={busy}
              >
                <Save className="h-4 w-4" /> Сохранить
              </Button>
              <Button
                variant="subtle"
                onClick={() => setConfirmAction('reset')}
                disabled={busy}
              >
                <RotateCcw className="h-4 w-4" /> По умолчанию
              </Button>
            </div>
          </div>
        ) : null}
      </section>

      <section className="flex min-h-0 flex-col overflow-hidden border border-white/10 bg-[var(--card-bg)]">
        <header className="border-b border-white/10 px-4 py-3">
          <h2 className="font-social text-sm uppercase tracking-wide">Стрим и пост</h2>
        </header>

        <div className="max-h-64 shrink-0 overflow-y-auto border-b border-white/10">
          {data.runs.length ? (
            data.runs.map((run) => (
              <RunRow
                key={run.id}
                run={run}
                active={run.id === target?.id}
                onSelect={() => setRunId(run.id)}
              />
            ))
          ) : (
            <EmptyState title="Завершённых стримов нет" />
          )}
        </div>

        <div className="flex min-h-0 flex-1 flex-col">
          <div className="border-b border-white/10 px-4 py-2.5 text-xs uppercase tracking-wide text-[var(--text-muted)]">
            Посты-кандидаты
          </div>
          <div className="min-h-0 max-h-[55vh] flex-1 overflow-y-auto">
            {data.announcements.length ? (
              data.announcements.map((post) => {
                const selected = target?.announcement_id === post.id
                return (
                  <div
                    key={post.id}
                    className={cn(
                      'border-b border-white/5 px-4 py-3',
                      selected ? 'bg-[var(--accent)]/10' : '',
                    )}
                  >
                    <div className="flex items-center justify-between gap-2 text-xs text-[var(--text-muted)]">
                      <span>
                        #{post.message_id} · {formatDateTime(post.posted_at)}
                      </span>
                      <span>{post.media_kind ? 'медиа' : 'текст'}</span>
                    </div>
                    <p className="mt-1 line-clamp-2 text-sm text-[var(--text)]">
                      {post.preview || 'Без текста'}
                    </p>
                    <div className="mt-2 flex items-center justify-between gap-2">
                      <span className="text-xs text-[var(--text-muted)]">
                        {post.link_urls.length
                          ? `Ссылок: ${post.link_urls.length}`
                          : 'Без ссылок'}
                      </span>
                      <Button
                        size="sm"
                        variant={selected ? 'subtle' : 'ghost'}
                        disabled={
                          !target || selected || busy || target.status === 'applying'
                        }
                        onClick={() => targetMutation.mutate(post.id)}
                      >
                        {selected ? 'Выбран' : 'Выбрать'}
                      </Button>
                    </div>
                  </div>
                )
              })
            ) : (
              <EmptyState
                title="Постов не найдено"
                hint="Посты появляются после публикации в канале."
              />
            )}
          </div>
        </div>
      </section>

      <section className="flex min-h-0 flex-col overflow-hidden border border-white/10 bg-[var(--card-bg)]">
        <header className="flex items-center justify-between gap-2 border-b border-white/10 px-4 py-3">
          <h2 className="font-social text-sm uppercase tracking-wide">Предпросмотр</h2>
          {target ? <StatusBadge status={target.status} /> : null}
        </header>

        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4">
          {target ? (
            <>
              <div className="text-sm">
                <div className="font-medium text-[var(--text)]">
                  {target.stream_title || `Стрим ${target.stream_id}`}
                </div>
                <div className="mt-1 text-xs text-[var(--text-muted)]">
                  {formatDateTime(target.stream_ended_at || target.stream_started_at)}
                  {target.announcement_id
                    ? ` · пост #${target.announcement_id}`
                    : ' · пост не выбран'}
                </div>
              </div>

              <div className="rounded-lg border border-white/10 bg-[#17212b] p-4 text-[15px] leading-relaxed text-white">
                {data.preview.text ? (
                  <div
                    className="whitespace-pre-wrap break-words [&_a]:text-[#6ab3f3] [&_a]:underline"
                    dangerouslySetInnerHTML={{ __html: data.preview.html }}
                  />
                ) : (
                  <span className="text-white/50">Пустой текст</span>
                )}
              </div>

              {target.last_error ? (
                <div className="flex items-start gap-2 rounded-md border border-red-400/20 bg-red-400/5 px-3 py-2 text-sm text-red-300">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>{target.last_error}</span>
                </div>
              ) : null}

              {checkResult ? (
                <div
                  className={cn(
                    'flex items-start gap-2 rounded-md border px-3 py-2 text-sm',
                    checkResult.available
                      ? 'border-emerald-400/20 bg-emerald-400/5 text-emerald-300'
                      : 'border-amber-400/20 bg-amber-400/5 text-amber-300',
                  )}
                >
                  <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
                  <span>
                    {checkResult.available
                      ? `VOD доступен${checkResult.duration_minutes ? `, ${checkResult.duration_minutes} мин` : ''}.`
                      : checkResult.error || 'VOD не найден.'}
                  </span>
                </div>
              ) : null}
            </>
          ) : (
            <EmptyState title="Выберите стрим" />
          )}
        </div>

        <div className="flex flex-wrap gap-2 border-t border-white/10 px-4 py-3">
          <Button
            variant="ghost"
            onClick={() => checkMutation.mutate()}
            disabled={!target || checkMutation.isPending}
          >
            Проверить VOD
          </Button>
          <Button
            variant="primary"
            onClick={() => setConfirmAction('publish')}
            disabled={!canPublish || busy}
          >
            <Send className="h-4 w-4" /> Опубликовать сейчас
          </Button>
          <Button
            variant="subtle"
            onClick={() => setConfirmAction('undo')}
            disabled={!canUndo || busy}
          >
            <Undo2 className="h-4 w-4" /> Отменить правку
          </Button>
          <Button
            variant="ghost"
            onClick={() => setConfirmAction('restore')}
            disabled={!canRestore || busy}
          >
            <RotateCcw className="h-4 w-4" /> Вернуть оригинал
          </Button>
        </div>
      </section>

      <ConfirmDialog
        open={confirmAction === 'reset'}
        title="Сбросить шаблон?"
        message="Заголовок, запись, разделитель, подвал, текст ссылки и задержка вернутся к значениям по умолчанию."
        confirmLabel="Сбросить"
        busy={resetMutation.isPending}
        onCancel={() => setConfirmAction(null)}
        onConfirm={() => resetMutation.mutate()}
      />
      <ConfirmDialog
        open={confirmAction === 'publish'}
        title="Опубликовать сейчас?"
        message="Бот проверит VOD и отредактирует выбранный пост, не дожидаясь задержки."
        confirmLabel="Опубликовать"
        busy={publishMutation.isPending}
        onCancel={() => setConfirmAction(null)}
        onConfirm={() => publishMutation.mutate()}
      />
      <ConfirmDialog
        open={confirmAction === 'undo'}
        title="Отменить правку?"
        message="Пост вернётся к состоянию до последней правки бота. Задание можно запустить снова."
        confirmLabel="Отменить правку"
        busy={undoMutation.isPending}
        onCancel={() => setConfirmAction(null)}
        onConfirm={() => undoMutation.mutate()}
      />
      <ConfirmDialog
        open={confirmAction === 'restore'}
        title="Вернуть оригинал?"
        message="Пост вернётся к первоначальному тексту анонса, все правки бота будут отменены."
        confirmLabel="Вернуть оригинал"
        busy={restoreMutation.isPending}
        onCancel={() => setConfirmAction(null)}
        onConfirm={() => restoreMutation.mutate()}
      />
    </div>
  )
}
