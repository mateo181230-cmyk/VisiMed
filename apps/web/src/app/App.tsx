import { lazy, Suspense } from 'react'
import { BrowserRouter, Navigate, Route, Routes, useLocation } from 'react-router-dom'
import { ToastProvider } from '../components/Toast'
import { TodayScreen } from '../features/agenda/TodayScreen'
import { WeekScreen } from '../features/agenda/WeekScreen'
import { AuthProvider, useAuth } from '../features/auth/AuthProvider'
import { AdminAccount } from '../features/intelligence/AdminAccount'
import { HistoryScreen } from '../features/history/HistoryScreen'
import { UbicacionPrueba } from '../features/geo/UbicacionPrueba'
import { LoginScreen } from '../features/auth/LoginScreen'
import { RegisterScreen } from '../features/auth/RegisterScreen'
import { MoreScreen } from '../features/notifications/MoreScreen'
import { NotificationsScreen } from '../features/notifications/NotificationsScreen'
import { PendingScreen } from '../features/notifications/PendingScreen'
import { LiveVisitScreen } from '../features/training/LiveVisitScreen'
import { ResultScreen } from '../features/training/ResultScreen'
import { ScenarioScreen } from '../features/training/ScenarioScreen'
import { TrainingHome } from '../features/training/TrainingHome'
import { SyncProvider } from '../sync/SyncProvider'
import { Shell } from './Shell'

const IntelligenceModule = lazy(() =>
  import('../features/intelligence/IntelligenceModule').then((m) => ({
    default: m.IntelligenceModule,
  })),
)
const TrainingBuilder = lazy(() =>
  import('../features/training-builder/TrainingBuilder').then((m) => ({
    default: m.TrainingBuilder,
  })),
)
const IntelligenceOverview = lazy(() =>
  import('../features/intelligence/OverviewScreen').then((m) => ({
    default: m.IntelligenceOverview,
  })),
)
const DoctorsScreen = lazy(() =>
  import('../features/intelligence/DoctorsScreen').then((m) => ({
    default: m.DoctorsScreen,
  })),
)
const DoctorProfileScreen = lazy(() =>
  import('../features/intelligence/DoctorProfileScreen').then((m) => ({
    default: m.DoctorProfileScreen,
  })),
)
const RecommendationsScreen = lazy(() =>
  import('../features/intelligence/RecommendationsScreen').then((m) => ({
    default: m.RecommendationsScreen,
  })),
)
const IntelligenceCalendar = lazy(() =>
  import('../features/intelligence/CalendarScreen').then((m) => ({
    default: m.IntelligenceCalendar,
  })),
)
const RecommendationDetailsScreen = lazy(() =>
  import('../features/intelligence/RecommendationDetailsScreen').then((m) => ({
    default: m.RecommendationDetailsScreen,
  })),
)
const IntelligenceOptionsScreen = lazy(() =>
  import('../features/intelligence/IntelligenceOptionsScreen').then((m) => ({
    default: m.IntelligenceOptionsScreen,
  })),
)
const LearningScreen = lazy(() =>
  import('../features/intelligence/LearningScreen').then((m) => ({
    default: m.LearningScreen,
  })),
)

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { status } = useAuth()
  const location = useLocation()
  if (status === 'loading') return <div className="min-h-dvh" aria-busy />
  if (status === 'anon') return <Navigate to="/login" state={{ from: location.pathname + location.search }} replace />
  return <>{children}</>
}

const PilotDemoScreen = lazy(() =>
  import('../features/intelligence/PilotDemoScreen').then((m) => ({
    default: m.PilotDemoScreen,
  })),
)

function RoleAwareShell() {
  const { user } = useAuth()
  const { pathname } = useLocation()
  // La gerencia aterriza antes del permiso de GPS que exige el marco del visitador.
  return pathname === '/' && (user?.role === 'admin' || user?.role === 'manager') ? (
    <Navigate to={user.role === 'admin' ? '/inteligencia/resumen' : '/inteligencia'} replace />
  ) : (
    <Shell />
  )
}

function IntelligenceHome() {
  const { user } = useAuth()
  const { pathname } = useLocation()
  return user?.role === 'admin' && !pathname.includes('/demo')
    ? <Navigate to="/inteligencia/resumen" replace />
    : <RecommendationsScreen />
}

function AdminHome() {
  const { user } = useAuth()
  return <Navigate to={user?.role === 'admin' ? '/inteligencia/resumen' : '/inteligencia'} replace />
}

const intelligenceViews = (
  <>
    <Route index element={<IntelligenceHome />} />
    <Route path="resumen" element={<IntelligenceOverview />} />
    <Route path="cuenta" element={<AdminAccount />} />
    <Route path="opciones" element={<IntelligenceOptionsScreen />} />
    <Route path="medicos" element={<DoctorsScreen />} />
    <Route path="medicos/:doctorId" element={<DoctorProfileScreen />} />
    <Route path="recomendaciones" element={<RecommendationsScreen />} />
    <Route path="recomendaciones/:recommendationId" element={<RecommendationDetailsScreen />} />
    <Route path="calendario" element={<IntelligenceCalendar />} />
    <Route path="aprendizaje" element={<LearningScreen />} />
    <Route path="visita" element={<PilotDemoScreen />} />
    <Route path="*" element={<RecommendationsScreen />} />
  </>
)

export function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <SyncProvider>
          <ToastProvider>
            <Suspense
              fallback={
                <div className="grid min-h-dvh place-items-center text-muted" role="status">
                  Abriendo módulo…
                </div>
              }
            >
              <Routes>
                <Route path="/login" element={<LoginScreen />} />
                <Route path="/registro" element={<RegisterScreen />} />
                <Route path="/admin" element={<RequireAuth><AdminHome /></RequireAuth>} />
                <Route path="/admin/training/demo/:levelId?" element={<TrainingBuilder demo />} />
                <Route
                  path="/admin/training/:levelId?"
                  element={<RequireAuth><TrainingBuilder /></RequireAuth>}
                />
                {/* El ejemplo usa solo datos ficticios; no exige login ni escribe en /v1/sync. */}
                <Route path="/inteligencia/demo" element={<IntelligenceModule preview />}>
                  {intelligenceViews}
                </Route>
                {/* Consultar recomendaciones no requiere GPS y conserva la navegación del visitador. */}
                <Route
                  path="/inteligencia"
                  element={
                    <RequireAuth>
                      <IntelligenceModule />
                    </RequireAuth>
                  }
                >
                  {intelligenceViews}
                </Route>
                <Route
                  element={
                    <RequireAuth>
                      <RoleAwareShell />
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
            </Suspense>
          </ToastProvider>
        </SyncProvider>
      </AuthProvider>
    </BrowserRouter>
  )
}
