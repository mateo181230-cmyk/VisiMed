import { ArrowLeft, MoreHorizontal, Sparkles, LayoutDashboard, GraduationCap, Stethoscope, SlidersHorizontal, ShieldCheck } from "lucide-react";
import { useEffect } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import { BottomNav } from "../../components/BottomNav";
import { ProfileLink } from "../../components/ProfileLink";
import { ScreenHeader } from "../../components/ScreenHeader";
import { useAuth } from "../auth/AuthProvider";
import { usePwaUpdate } from '../../pwa';
import { IntelligenceProvider, useIntelligence } from "./IntelligenceProvider";
import "./intelligence.css";
import "./mobile.css";
import "./admin.css";

export function IntelligenceModule({ preview = false }: { preview?: boolean }) {
  return (
    <IntelligenceProvider preview={preview}>
      <IntelligenceLayout preview={preview} />
    </IntelligenceProvider>
  );
}

function IntelligenceLayout({ preview }: { preview: boolean }) {
  const { path, mode, loading, loadError, refresh } = useIntelligence();
  const { pathname } = useLocation();
  const { user } = useAuth();
  const { needRefresh, update } = usePwaUpdate();
  const admin = !preview && user?.role === 'admin';
  const home = pathname === path() || pathname === path("recomendaciones");
  const options = pathname === path("opciones");
  const coreHeader = home && !preview;
  useEffect(() => {
    window.scrollTo({ top: 0 });
  }, [pathname]);
  if (admin) {
    return (
      <div className="intel-app intel-mobile-app intel-admin-layout">
        <a href="#intel-main" className="intel-skip-link">Saltar al contenido</a>
        <aside className="intel-admin-sidebar">
          <Link to="/admin" className="intel-admin-brand">uno<span>.</span><small>NOVAMED</small></Link>
          <p>ADMINISTRACIÓN</p>
          <nav aria-label="Panel de administrador">
            <Link to={path('resumen')} aria-current={pathname === path('resumen') ? 'page' : undefined}><LayoutDashboard size={20} /> Dashboard</Link>
            <Link to="/admin/training"><GraduationCap size={20} /> Training Builder <small>Demo</small></Link>
            <Link to={path('medicos')} aria-current={pathname.startsWith(path('medicos')) ? 'page' : undefined}><Stethoscope size={20} /> Perfiles médicos</Link>
            <Link to={path('opciones')} aria-current={options ? 'page' : undefined}><SlidersHorizontal size={20} /> Más opciones</Link>
          </nav>
          <div className="intel-admin-user"><ShieldCheck size={21} /><div><strong>{user.full_name}</strong><span>Administrador</span></div></div>
        </aside>
        <div className="intel-admin-content">
          <header className="intel-admin-header"><div><strong>Panel de administrador</strong><span>Actividad del equipo y configuración de entrenamiento</span></div><ProfileLink to={path('cuenta')} /></header>
          <main id="intel-main" className="intel-main" tabIndex={-1}>
            {needRefresh && <div role="status"><p>Hay una versión nueva de UNO.</p><button type="button" className="intel-button intel-button--secondary" onClick={update}>Actualizar aplicación</button></div>}
            {pathname !== path('resumen') && <section className="intel-admin-training"><div><span>ENTRENAMIENTO TAVUS</span><h2>Diseña el próximo nivel de tu equipo</h2><p>Agrega niveles y configura objetivos, pesos y puntajes de aprobación.</p><small>Training Builder en demostración · los cambios se guardan en este navegador.</small></div><Link to="/admin/training">Abrir Training Builder <GraduationCap size={19} /></Link></section>}
            <div className="intel-admin-data"><span>{mode === 'demo' ? 'Datos de ejemplo' : mode === 'empty' ? 'Sin datos' : 'Reportes registrados en UNO'}</span><button type="button" className="intel-text-link" disabled={loading && mode !== 'demo'} onClick={refresh}>{loading && mode !== 'demo' ? 'Actualizando reportes…' : 'Actualizar reportes'}</button></div>
            {loading && <p role="status">Consultando visitas y reportes…</p>}
            {loadError && <p role="alert">{loadError}</p>}
            <Outlet />
          </main>
        </div>
      </div>
    );
  }
  return (
    <div className="intel-app intel-mobile-app">
      <a href="#intel-main" className="intel-skip-link">
        Saltar al contenido
      </a>
      {coreHeader ? (
        <ScreenHeader title="Recomendaciones" subtitle="Tu siguiente visita, en un vistazo." right={<ProfileLink />} />
      ) : <header className="intel-mobile-header">
        {home ? (
          <Link
            to={path()}
            className="intel-mobile-brand"
            aria-label="UNO Visitas · Recomendaciones"
          >
            uno<span>.</span>
          </Link>
        ) : (
          <Link
            to={path()}
            className="intel-mobile-back"
            aria-label="Volver a recomendaciones"
          >
            <ArrowLeft size={21} /> Volver
          </Link>
        )}
        <div className="intel-mobile-header-actions">
          {mode === "demo" && (
            <span
              className="intel-demo-pill"
              aria-label="Datos simulados para el piloto"
            >
              Ejemplo
            </span>
          )}
          {!options && (
            <Link
              to={path("opciones")}
              className="intel-icon-button"
              aria-label="Más opciones del módulo"
            >
              <MoreHorizontal size={23} />
            </Link>
          )}
          {!preview && <ProfileLink />}
        </div>
      </header>}
      <main id="intel-main" className="intel-main" tabIndex={-1}>
        {needRefresh && <div role="status"><p>Hay una versión nueva de UNO.</p><button type="button" className="intel-button intel-button--secondary" onClick={update}>Actualizar aplicación</button></div>}
        {loading && <p role="status">Consultando visitas y reportes…</p>}
        {loadError && (
          <div role="alert">
            <p>{loadError}</p>
            <button
              className="intel-button intel-button--secondary"
              type="button"
              onClick={refresh}
            >
              Actualizar reportes
            </button>
          </div>
        )}
        {coreHeader && (
          <div className="mb-4 flex min-h-11 items-center justify-end">
            <Link to={path("opciones")} className="intel-text-link inline-flex items-center gap-2" aria-label="Más opciones del módulo">
              Más opciones <MoreHorizontal size={20} />
            </Link>
          </div>
        )}
        {mode === "live" && (
          <button type="button" className="intel-text-link" onClick={refresh}>
            Actualizar reportes
          </button>
        )}
        <Outlet context={{ coreHeader }} />
      </main>
      {mode === "demo" && (
        <p className="intel-mobile-demo-note">
          <Sparkles size={13} /> Vista con datos de ejemplo.
        </p>
      )}
      <BottomNav
        recommendationsPath={path()}
        agendaPath={preview ? path("calendario") : "/agenda"}
        section={pathname === path("calendario") ? "agenda" : "recommendations"}
      />
    </div>
  );
}
