import { api } from '@/api/client'
import type { ChannelInfo } from '@/api/types'
import type { MetaList } from '@/types/api'

export async function listGenres(): Promise<MetaList> {
  const { data } = await api.get<MetaList>('/meta/genres')
  return data
}

export async function listPlatforms(): Promise<MetaList> {
  const { data } = await api.get<MetaList>('/meta/platforms')
  return data
}

/** Данные канала: логин, имя и аватар (`profile_image_url`). */
export async function getChannel(): Promise<ChannelInfo> {
  const { data } = await api.get<ChannelInfo>('/meta/channel')
  return data
}
