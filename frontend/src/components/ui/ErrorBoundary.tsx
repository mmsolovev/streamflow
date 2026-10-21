import { Component } from 'react'
import type { ErrorInfo, ReactNode } from 'react'

import { Button } from '@/components/ui/Button'

interface ErrorBoundaryProps {
  children: ReactNode
  /** Что показать при ошибке (по умолчанию — сообщение с кнопкой «Обновить»). */
  fallback?: (error: Error, reset: () => void) => ReactNode
}

interface ErrorBoundaryState {
  error: Error | null
}

/**
 * Граница ошибок: ловит ошибки рендера и показывает понятное сообщение
 * вместо пустого (белого) экрана.
 */
export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  state: ErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('ErrorBoundary: ошибка в приложении', error, info.componentStack)
  }

  reset = () => {
    this.setState({ error: null })
  }

  render() {
    const { error } = this.state
    if (!error) return this.props.children

    if (this.props.fallback) {
      return this.props.fallback(error, this.reset)
    }

    return (
      <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 p-8 text-center">
        <h1 className="font-social text-xl uppercase tracking-wide text-[var(--text)]">
          Что-то пошло не так
        </h1>
        <p className="max-w-md text-sm text-[var(--text-muted)]">
          Страница не смогла отобразиться. Обновите её — если ошибка повторяется,
          проверьте консоль браузера.
        </p>
        {error.message ? (
          <pre className="max-w-xl overflow-x-auto rounded-md border border-white/10 bg-black/30 px-4 py-2 text-left text-xs text-[var(--text-muted)]">
            {error.message}
          </pre>
        ) : null}
        <div className="flex items-center gap-2">
          <Button onClick={this.reset}>Попробовать снова</Button>
          <Button variant="ghost" onClick={() => window.location.reload()}>
            Обновить страницу
          </Button>
        </div>
      </div>
    )
  }
}
