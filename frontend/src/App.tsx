import { Navigate, Route, Routes } from 'react-router-dom'

import { AppLayout } from '@/components/layout/AppLayout'
import { ProtectedRoute } from '@/features/auth/ProtectedRoute'
import { AdminPage } from '@/pages/AdminPage'
import { BotPage } from '@/pages/BotPage'
import { GameDetailPage } from '@/pages/GameDetailPage'
import { NotFoundPage } from '@/pages/NotFoundPage'
import { PlaceholderPage } from '@/pages/PlaceholderPage'
import { StatsPage } from '@/pages/StatsPage'

export default function App() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<Navigate to="/games" replace />} />
        <Route path="stats/*" element={<Navigate to="/games" replace />} />
        <Route path="games/:gameId" element={<GameDetailPage />} />
        <Route path="games" element={<StatsPage section="games" />} />
        <Route path="streams" element={<StatsPage section="streams" />} />
        <Route path="releases" element={<StatsPage section="releases" />} />
        <Route path="recommendations" element={<StatsPage section="recommendations" />} />
        <Route path="hltb" element={<StatsPage section="hltb" />} />
        <Route path="bot" element={<Navigate to="/bot/commands" replace />} />
        <Route path="bot/commands" element={<BotPage section="commands" />} />
        <Route
          path="events"
          element={<PlaceholderPage title="Ивенты" note="Раздел в разработке." />}
        />
        <Route
          path="interactive"
          element={
            <PlaceholderPage
              title="Интерактив"
              note="Миниигры: лото на билетах из чата и другие."
            />
          }
        />
        <Route
          path="admin"
          element={
            <ProtectedRoute requireAdmin>
              <Navigate to="/admin/management" replace />
            </ProtectedRoute>
          }
        />
        <Route
          path="admin/management"
          element={
            <ProtectedRoute requireAdmin>
              <AdminPage section="management" />
            </ProtectedRoute>
          }
        />
        <Route
          path="admin/connections"
          element={
            <ProtectedRoute requireAdmin>
              <AdminPage section="connections" />
            </ProtectedRoute>
          }
        />
        <Route
          path="admin/telegram"
          element={
            <ProtectedRoute requireAdmin>
              <AdminPage section="telegram" />
            </ProtectedRoute>
          }
        />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}
