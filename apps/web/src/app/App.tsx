import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { ToastProvider } from '../components/Toast'
import { TodayScreen } from '../features/agenda/TodayScreen'
import { WeekScreen } from '../features/agenda/WeekScreen'
import { AuthProvider, useAuth } from '../features/auth/AuthProvider'
import { HistoryScreen } from '../features/history/HistoryScreen'
import { UbicacionPrueba } from '../features/geo/UbicacionPrueba'
import { LoginScreen } from '../features/auth/LoginScreen'
import { MoreScreen } from '../features/notifications/MoreScreen'
import { NotificationsScreen } from '../features/notifications/NotificationsScreen'
import { PendingScreen } from '../features/notifications/PendingScreen'
import { LiveVisitScreen } from '../features/training/LiveVisitScreen'
import { ResultScreen } from '../features/training/ResultScreen'
import { ScenarioScreen } from '../features/training/ScenarioScreen'
import { TrainingHome } from '../features/training/TrainingHome'
import { SyncProvider } from '../sync/SyncProvider'
import { Shell } from './Shell'

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { status } = useAuth()
  if (status === 'loading') return <div className="min-h-dvh" aria-busy />
  if (status === 'anon') return <Navigate to="/login" replace />
  return <>{children}</>
}

export function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <SyncProvider>
          <ToastProvider>
            <Routes>
              <Route path="/login" element={<LoginScreen />} />
              <Route
                element={
                  <RequireAuth>
                    <Shell />
                  </RequireAuth>
                }
              >
                <Route index element={<TodayScreen />} />
                <Route path="agenda" element={<WeekScreen />} />
                <Route path="historial" element={<HistoryScreen />} />
                <Route path="mas" element={<MoreScreen />} />
                <Route path="mas/avisos" element={<NotificationsScreen />} />
                <Route path="mas/pendientes" element={<PendingScreen />} />
                <Route path="mas/ubicacion" element={<UbicacionPrueba />} />
                <Route path="entrenar" element={<TrainingHome />} />
                <Route path="entrenar/:slug" element={<ScenarioScreen />} />
                <Route path="entrenar/intento/:attemptId" element={<ResultScreen />} />
              </Route>
              {/* La visita va a pantalla completa, sin barra inferior. */}
              <Route
                path="/entrenar/visita/:attemptId"
                element={
                  <RequireAuth>
                    <LiveVisitScreen />
                  </RequireAuth>
                }
              />
              <Route path="*" element={<Navigate to="/" replace />} />
            </Routes>
          </ToastProvider>
        </SyncProvider>
      </AuthProvider>
    </BrowserRouter>
  )
}
