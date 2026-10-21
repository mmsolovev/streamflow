import { useQuery } from '@tanstack/react-query'

import { getChannel, listGenres, listPlatforms } from '@/features/meta/api'

export function useGenres() {
  return useQuery({
    queryKey: ['meta', 'genres'],
    queryFn: listGenres,
    staleTime: Infinity,
  })
}

export function usePlatforms() {
  return useQuery({
    queryKey: ['meta', 'platforms'],
    queryFn: listPlatforms,
    staleTime: Infinity,
  })
}

/** Данные канала (аватар, имя) — для боковых панелей. */
export function useChannel() {
  return useQuery({
    queryKey: ['meta', 'channel'],
    queryFn: getChannel,
    staleTime: 60 * 60_000,
  })
}
