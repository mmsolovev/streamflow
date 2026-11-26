import { api } from '@/api/client'
import type { SocialLinkView } from '@/api/types'

export type { SocialLinkView } from '@/api/types'

export function listSocialLinks(): Promise<SocialLinkView[]> {
  return api
    .get<SocialLinkView[]>('/media/social-links')
    .then((response) => response.data)
}

export interface SocialLinkCreate {
  service_key: string
  name: string
  url: string
  description: string
  sort_order: number
  is_active: boolean
}

export interface SocialLinkUpdate {
  name?: string
  url?: string
  description?: string
  sort_order?: number
  is_active?: boolean
}

export function listAdminSocialLinks(): Promise<SocialLinkView[]> {
  return api
    .get<SocialLinkView[]>('/admin/links')
    .then((response) => response.data)
}

export function createSocialLink(body: SocialLinkCreate): Promise<SocialLinkView> {
  return api
    .post<SocialLinkView>('/admin/links', body)
    .then((response) => response.data)
}

export function updateSocialLink(
  id: number,
  body: SocialLinkUpdate,
): Promise<SocialLinkView> {
  return api
    .patch<SocialLinkView>(`/admin/links/${id}`, body)
    .then((response) => response.data)
}

export async function deleteSocialLink(id: number): Promise<void> {
  await api.delete(`/admin/links/${id}`)
}

export function uploadSocialIcon(id: number, file: File): Promise<{ id: number; icon_url: string }> {
  const form = new FormData()
  form.append('file', file)
  return api
    .post<{ id: number; icon_url: string }>(`/admin/links/${id}/icon/file`, form)
    .then((response) => response.data)
}

export function setSocialIconUrl(
  id: number,
  url: string,
): Promise<{ id: number; icon_url: string }> {
  return api
    .put<{ id: number; icon_url: string }>(`/admin/links/${id}/icon/url`, { url })
    .then((response) => response.data)
}

export async function deleteSocialIcon(id: number): Promise<void> {
  await api.delete(`/admin/links/${id}/icon`)
}
