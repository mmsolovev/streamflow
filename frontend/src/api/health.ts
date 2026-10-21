import { api } from '@/api/client'
import type { Health } from '@/api/types'

export async function getHealth(): Promise<Health> {
  const { data } = await api.get<Health>('/health')
  return data
}
