import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import type { BotCommandCreateBody, BotCommandsPage } from '@/api/types'
import {
  createBotCommand,
  listBotCommands,
  updateBotCommandState,
} from '@/features/bot/api'
import type { BotCommandListParams, BotCommandStatePatch } from '@/features/bot/api'

/** Команды бота с серверными поиском, сортировкой и пагинацией. */
export function useBotCommandsList(params: BotCommandListParams) {
  return useQuery({
    queryKey: ['bot-commands', 'list', params],
    queryFn: () => listBotCommands(params),
    placeholderData: (previous) => previous,
  })
}

/** Добавление команды другого бота в реестр. */
export function useCreateBotCommand() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (body: BotCommandCreateBody) => createBotCommand(body),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['bot-commands'] })
      toast.success('Команда добавлена.')
    },
    onError: (error) => {
      toast.error(error.message)
    },
  })
}

export interface BotCommandStateVariables {
  commandId: number
  patch: BotCommandStatePatch
}

/**
 * Переключение `is_visible` / `is_active`.
 *
 * Обновление оптимистичное: флаг меняется сразу, при ошибке возвращается
 * прежнее значение.
 */
export function useUpdateBotCommandState() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ commandId, patch }: BotCommandStateVariables) =>
      updateBotCommandState(commandId, patch),
    onMutate: async ({ commandId, patch }) => {
      await queryClient.cancelQueries({ queryKey: ['bot-commands'] })
      const previous = queryClient.getQueriesData<BotCommandsPage>({
        queryKey: ['bot-commands', 'list'],
      })
      // Список кешируется по параметрам — обновляем все его варианты.
      queryClient.setQueriesData<BotCommandsPage>(
        { queryKey: ['bot-commands', 'list'] },
        (old) =>
          old
            ? {
                ...old,
                items: old.items.map((command) =>
                  command.id === commandId ? { ...command, ...patch } : command,
                ),
              }
            : old,
      )
      return { previous }
    },
    onError: (error, _variables, context) => {
      context?.previous?.forEach(([key, data]) => {
        queryClient.setQueryData(key, data)
      })
      toast.error(error.message)
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ['bot-commands'] })
    },
  })
}
