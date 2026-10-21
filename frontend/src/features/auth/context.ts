import { createContext, useContext } from 'react'

import type { UserView } from '@/api/types'

export interface AuthValue {
  user: UserView | null
  isLoading: boolean
  isAuthenticated: boolean
  isStreamer: boolean
  isAdmin: boolean
  /** Может менять данные: стример или админ. */
  canEdit: boolean
  refetch: () => void
}

export const AuthContext = createContext<AuthValue | undefined>(undefined)

export function useAuth(): AuthValue {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within <AuthProvider>')
  }
  return context
}
