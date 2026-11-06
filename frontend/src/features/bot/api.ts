import { api } from '@/api/client'
import type { BotCommandCreateBody, BotCommandView, BotCommandsPage } from '@/api/types'

export interface BotCommandListParams {
  search?: string
  sort?: string
  direction?: 'asc' | 'desc'
  limit: number
  offset: number
}

/** Частичное обновление флагов команды. */
export interface BotCommandStatePatch {
  is_visible?: boolean
  is_active?: boolean
}

/** Список команд из реестра `bot_commands`. */
export function listBotCommands(params: BotCommandListParams): Promise<BotCommandsPage> {
  return api
    .get<BotCommandsPage>('/bot-commands', { params })
    .then((response) => response.data)
}

/** Добавляет команду другого бота в реестр (только администратор). */
export async function createBotCommand(
  body: BotCommandCreateBody,
): Promise<BotCommandView> {
  const { data } = await api.post<BotCommandView>('/bot-commands', body)
  return data
}

/** Переключает видимость/активность команды (только администратор). */
export async function updateBotCommandState(
  commandId: number,
  body: BotCommandStatePatch,
): Promise<BotCommandView> {
  const { data } = await api.patch<BotCommandView>(`/bot-commands/${commandId}`, body)
  return data
}
