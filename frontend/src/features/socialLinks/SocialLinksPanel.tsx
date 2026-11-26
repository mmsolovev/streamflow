import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ImagePlus, Plus, Save, Trash2 } from 'lucide-react'
import { toast } from 'sonner'

import { ConfirmDialog } from '@/components/ui/ConfirmDialog'
import { EmptyState } from '@/components/ui/EmptyState'
import { ErrorState } from '@/components/ui/ErrorState'
import { Skeleton } from '@/components/ui/Skeleton'
import {
  createSocialLink,
  deleteSocialIcon,
  deleteSocialLink,
  listAdminSocialLinks,
  setSocialIconUrl,
  updateSocialLink,
  uploadSocialIcon,
  type SocialLinkUpdate,
} from './api'
import type { SocialLinkView } from './api'

function SocialLinkRow({
  link,
  onSave,
  onDelete,
  onUploadIcon,
  onSetIconUrl,
  onRemoveIcon,
}: {
  link: SocialLinkView
  onSave: (body: SocialLinkUpdate) => void
  onDelete: () => void
  onUploadIcon: (file: File) => void
  onSetIconUrl: (url: string) => void
  onRemoveIcon: () => void
}) {
  const [name, setName] = useState(link.name)
  const [url, setUrl] = useState(link.url)
  const [description, setDescription] = useState(link.description)
  const [sortOrder, setSortOrder] = useState(String(link.sort_order))
  const [active, setActive] = useState(link.is_active)
  const [iconUrl, setIconUrl] = useState('')
  const dirty =
    name !== link.name ||
    url !== link.url ||
    description !== link.description ||
    sortOrder !== String(link.sort_order) ||
    active !== link.is_active

  return (
    <article className="grid gap-4 rounded-lg border border-white/10 bg-[var(--card-bg)] p-4 xl:grid-cols-[minmax(180px,1fr)_minmax(220px,1.4fr)_minmax(220px,1.4fr)_90px_auto]">
      <div className="flex items-center gap-3">
        <div className="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-md bg-white/5">
          {link.icon_url ? (
            <img src={link.icon_url} alt="" className="h-8 w-8 object-contain" />
          ) : (
            <ImagePlus className="h-5 w-5 text-[var(--text-muted)]" />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <label className="mb-1 block text-[10px] uppercase text-[var(--text-muted)]">
            Сервис
          </label>
          <input
            value={name}
            onChange={(event) => setName(event.target.value)}
            className="w-full rounded border border-white/10 bg-[var(--section-bg)] px-2 py-1.5 text-sm text-[var(--text)]"
          />
          <p className="mt-1 truncate text-[10px] text-[var(--text-muted)]">
            key: {link.service_key}
          </p>
        </div>
      </div>

      <label className="block text-[10px] uppercase text-[var(--text-muted)]">
        Ссылка
        <input
          value={url}
          onChange={(event) => setUrl(event.target.value)}
          placeholder="https://..."
          className="mt-1 w-full rounded border border-white/10 bg-[var(--section-bg)] px-2 py-1.5 text-sm normal-case text-[var(--text)]"
        />
      </label>

      <label className="block text-[10px] uppercase text-[var(--text-muted)]">
        Описание
        <input
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          placeholder="Короткое описание"
          className="mt-1 w-full rounded border border-white/10 bg-[var(--section-bg)] px-2 py-1.5 text-sm normal-case text-[var(--text)]"
        />
      </label>

      <label className="block text-[10px] uppercase text-[var(--text-muted)]">
        Порядок
        <input
          type="number"
          value={sortOrder}
          onChange={(event) => setSortOrder(event.target.value)}
          className="mt-1 w-full rounded border border-white/10 bg-[var(--section-bg)] px-2 py-1.5 text-sm text-[var(--text)]"
        />
      </label>

      <div className="flex flex-wrap items-end gap-2">
        <label className="flex h-9 cursor-pointer items-center gap-2 rounded border border-white/10 px-2 text-xs text-[var(--text-muted)] hover:text-[var(--text)]">
          <ImagePlus className="h-4 w-4" />
          Файл
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp,image/gif"
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0]
              if (file) onUploadIcon(file)
              event.currentTarget.value = ''
            }}
          />
        </label>
        <button
          type="button"
          disabled={!iconUrl.trim()}
          onClick={() => onSetIconUrl(iconUrl.trim())}
          className="h-9 rounded border border-white/10 px-2 text-xs text-[var(--text-muted)] hover:text-[var(--text)] disabled:opacity-40"
          title="Установить иконку по URL"
        >
          URL иконки
        </button>
        {link.icon_url ? (
          <button
            type="button"
            onClick={onRemoveIcon}
            className="h-9 rounded border border-red-400/20 px-2 text-xs text-red-300 hover:bg-red-400/10"
            title="Убрать иконку"
          >
            Убрать иконку
          </button>
        ) : null}
        <input
          value={iconUrl}
          onChange={(event) => setIconUrl(event.target.value)}
          placeholder="https://…"
          aria-label={`URL иконки для ${link.name}`}
          className="h-9 min-w-32 flex-1 rounded border border-white/10 bg-[var(--section-bg)] px-2 text-xs text-[var(--text)]"
        />
        <label className="flex h-9 items-center gap-1.5 rounded border border-white/10 px-2 text-xs text-[var(--text-muted)]">
          <input
            type="checkbox"
            checked={active}
            onChange={(event) => setActive(event.target.checked)}
          />
          Активна
        </label>
        <button
          type="button"
          disabled={!dirty}
          onClick={() =>
            onSave({
              name,
              url,
              description,
              sort_order: Number(sortOrder) || 0,
              is_active: active,
            })
          }
          className="flex h-9 items-center gap-1.5 rounded bg-[var(--accent)] px-3 text-xs font-medium text-black disabled:opacity-40"
          title="Сохранить"
        >
          <Save className="h-3.5 w-3.5" />
          Сохранить
        </button>
        <button
          type="button"
          onClick={onDelete}
          className="flex h-9 items-center gap-1.5 rounded border border-red-400/20 px-2 text-xs text-red-300 hover:bg-red-400/10"
          title="Удалить ссылку"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      </div>
    </article>
  )
}

export function SocialLinksPanel() {
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: ['admin-social-links'],
    queryFn: listAdminSocialLinks,
  })
  const [deleteTarget, setDeleteTarget] = useState<SocialLinkView | null>(null)
  const links = query.data ?? []

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['admin-social-links'] })
    void queryClient.invalidateQueries({ queryKey: ['social-links'] })
  }
  const createMutation = useMutation({
    mutationFn: createSocialLink,
    onSuccess: () => {
      invalidate()
      toast.success('Ссылка добавлена.')
    },
    onError: (error: Error) => toast.error(error.message),
  })
  const updateMutation = useMutation({
    mutationFn: ({ id, body }: { id: number; body: SocialLinkUpdate }) =>
      updateSocialLink(id, body),
    onSuccess: () => {
      invalidate()
      toast.success('Ссылка сохранена.')
    },
    onError: (error: Error) => toast.error(error.message),
  })
  const deleteMutation = useMutation({
    mutationFn: deleteSocialLink,
    onSuccess: () => {
      invalidate()
      setDeleteTarget(null)
      toast.success('Ссылка удалена.')
    },
    onError: (error: Error) => toast.error(error.message),
  })
  const uploadMutation = useMutation({
    mutationFn: ({ id, file }: { id: number; file: File }) =>
      uploadSocialIcon(id, file),
    onSuccess: () => {
      invalidate()
      toast.success('Иконка обновлена.')
    },
    onError: (error: Error) => toast.error(error.message),
  })
  const iconUrlMutation = useMutation({
    mutationFn: ({ id, url }: { id: number; url: string }) =>
      setSocialIconUrl(id, url),
    onSuccess: () => {
      invalidate()
      toast.success('Иконка обновлена.')
    },
    onError: (error: Error) => toast.error(error.message),
  })
  const removeIconMutation = useMutation({
    mutationFn: deleteSocialIcon,
    onSuccess: () => {
      invalidate()
      toast.success('Иконка удалена.')
    },
    onError: (error: Error) => toast.error(error.message),
  })

  const nextOrder = Math.max(0, ...links.map((link) => link.sort_order)) + 10

  if (query.isLoading) {
    return (
      <div className="space-y-3 p-6">
        <Skeleton className="h-20" />
        <Skeleton className="h-20" />
        <Skeleton className="h-20" />
      </div>
    )
  }
  if (query.isError) {
    return <ErrorState error={query.error} onRetry={() => void query.refetch()} />
  }

  return (
    <>
      <div className="space-y-4 p-4 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-[var(--text-muted)]">
            Эти ссылки отображаются в меню канала в левом верхнем углу.
          </p>
          <button
            type="button"
            disabled={createMutation.isPending}
            onClick={() =>
              createMutation.mutate({
                service_key: `service-${Date.now()}`,
                name: 'Новый сервис',
                url: '#',
                description: '',
                sort_order: nextOrder,
                is_active: true,
              })
            }
            className="flex items-center gap-2 rounded-md bg-[var(--accent)] px-3 py-2 text-sm font-medium text-black disabled:opacity-50"
          >
            <Plus className="h-4 w-4" />
            Добавить ссылку
          </button>
        </div>

        {links.length === 0 ? (
          <EmptyState title="Ссылок пока нет" />
        ) : (
          <div className="space-y-3">
            {links.map((link) => (
              <SocialLinkRow
                key={link.id}
                link={link}
                onSave={(body) => updateMutation.mutate({ id: link.id, body })}
                onDelete={() => setDeleteTarget(link)}
                onUploadIcon={(file) => uploadMutation.mutate({ id: link.id, file })}
                onSetIconUrl={(url) =>
                  iconUrlMutation.mutate({ id: link.id, url })
                }
                onRemoveIcon={() => removeIconMutation.mutate(link.id)}
              />
            ))}
          </div>
        )}
      </div>
      <ConfirmDialog
        open={deleteTarget !== null}
        title="Удалить ссылку?"
        message={
          deleteTarget
            ? `«${deleteTarget.name}» будет удалена из выпадающего меню.`
            : undefined
        }
        busy={deleteMutation.isPending}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={() => {
          if (deleteTarget) deleteMutation.mutate(deleteTarget.id)
        }}
      />
    </>
  )
}
