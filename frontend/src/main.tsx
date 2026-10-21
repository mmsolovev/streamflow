import { QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { Toaster } from 'sonner'

import App from '@/App.tsx'
import { queryClient } from '@/app/queryClient'
import { ErrorBoundary } from '@/components/ui/ErrorBoundary'
import { AuthProvider } from '@/features/auth/AuthProvider'
import '@/index.css'
import '@/styles/fonts'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <ErrorBoundary>
            <App />
          </ErrorBoundary>
          <Toaster theme="dark" position="bottom-right" />
        </AuthProvider>
      </QueryClientProvider>
    </BrowserRouter>
  </StrictMode>,
)
