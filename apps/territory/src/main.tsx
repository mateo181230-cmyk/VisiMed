import {PotentialInsights,PotentialMix} from './PotentialInsights';
import { TaskScreen, LibraryScreen, BriefScreen, ExecutionPanel } from "./Workflows";
import { MarketingScreen } from "./Marketing";
import { ManagementScreen } from "./Management";
import {AppNavigation} from './AppNavigation';
import {StudyScreen} from './Study';
import React, { useEffect, useMemo, useState, useRef } from "react";
import { createRoot } from "react-dom/client";
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  ChevronRight,
  Clock,
  MapPin,
  Navigation,
  Route,
  Search,
  Settings2,
  Store,
  Users,
  WifiOff,
  X,
  Plus,
  LocateFixed,
  RefreshCw,
  AlertCircle,
  CalendarDays,
  FileCheck2,
  Target,
  BookOpen,
  MoreHorizontal,
} from "lucide-react";
import {
  api,
  ApiError,
  cachedUser,
  db,
  flush,
  locate,
  login,
  readState,
  send,
  session,
  type User,
  type Pending,
} from "./api";
import { TerritoryMap } from "./Map";
import "./style.css";
import { VoiceReport } from "./VoiceReport";
import {CalendarScreen} from './Calendar';
import {DemoScreen} from './Demo';

const today = () =>
  new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Bogota",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
const localTime = (iso: string) =>
  new Intl.DateTimeFormat("es-CO", {
    timeZone: "America/Bogota",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(iso));
const dateLabel = (iso: string) =>
  new Intl.DateTimeFormat("es-CO", {
    timeZone: "America/Bogota",
    day: "numeric",
    month: "short",
  }).format(new Date(iso));
const dateKey = (iso: string) =>
  new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Bogota",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(iso));
const requestedRep = new URLSearchParams(location.search).get("rep") || "";
// These screens load their own scoped data; do not also fetch the full territory.
const standaloneModule = ['study','calendar','today','demo','marketing','management','tasks','library','brief'].includes(new URLSearchParams(location.search).get('module') || '');
const requestedDay = new URLSearchParams(location.search).get("day");
const future = (n: number) => {
  const d = new Date(today() + "T12:00:00-05:00");
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
};
const emptyOpening = {
  weekdays: [0, 1, 2, 3, 4],
  opens: "08:00",
  closes: "17:00",
};
const labels: any = {
  "location.verify": "Verificación de sede",
  "potential.save": "Potencial médico",
  "availability.save": "Horario de recepción",
  "pharmacy.save": "Ficha de droguería",
  "pharmacy.visit.schedule": "Visita a droguería",
  "pharmacy.visit.arrive": "Llegada",
  "pharmacy.visit.finish": "Salida",
  "pharmacy.visit.not_done": "Visita no realizada",
  "pharmacy.visit.report": "Reporte de droguería",
  "referral.create": "Direccionamiento",
};
const prettyStatus: any = {
  scheduled: "Programada",
  in_progress: "En visita",
  finished: "Por documentar",
  confirmed: "Confirmada",
  not_done: "No realizada",
  in_call: "En entrevista",
  processing: "Procesando reporte",
  ready: "Reporte por confirmar",
  no_interview: "Sin entrevista",
  published: "Publicada",
  draft: "Por revisar",
  superseded: "Versión anterior",
  queued: "En cola",
  running: "Calculando",
  error: "Requiere revisión",
  done: "Calculada",
};
function optimistic(raw: any, pending: Pending[]) {
  const s = structuredClone(raw);
  for (const c of pending.filter((x) => !x.error)) {
    const p = c.payload;
    if (c.type === "potential.save") {
      const list = s.potentials,
        old = list.find((x: any) => x.doctor_id === p.doctor_id),
        entry = {
          doctor_id: p.doctor_id,
          institution_id: p.institution_id,
          data: p,
          version: c.expected_version + 1,
          summary: {
            weekly_consultations: p.practice_days.length * p.patients_per_day,
            score: null,
            stale: false,
          },
        };
      if (old) Object.assign(old, entry);
      else list.push(entry);
    }
    if (c.type === "location.verify") {
      const site = s.sites.find((x: any) => x.id === p.institution_id);
      if (site) {
        site.lat = p.lat;
        site.lng = p.lng;
      }
      const old = s.locations.find(
          (x: any) => x.institution_id === p.institution_id,
        ),
        entry = {
          institution_id: p.institution_id,
          version: c.expected_version + 1,
          status: "pending_sync",
          source: p.source,
        };
      if (old) Object.assign(old, entry);
      else s.locations.push(entry);
    }
    if (c.type === "pharmacy.visit.schedule")
      s.pharmacy_visits.push({
        ...p,
        representative_id: s.representative_id,
        version: 1,
        status: "scheduled",
        report: {},
      });
    if (
      c.type.startsWith("pharmacy.visit.") &&
      c.type !== "pharmacy.visit.schedule"
    ) {
      const v = s.pharmacy_visits.find((x: any) => x.id === p.id);
      if (v) {
        v.version = c.expected_version + 1;
        v.status = (
          {
            arrive: "in_progress",
            finish: "finished",
            not_done: "not_done",
            report: "confirmed",
          } as any
        )[c.type.split(".").at(-1)!];
        if (c.type.endsWith("report")) v.report = p;
      }
    }
  }
  return s;
}

function Field({ label, hint, children }: any) {
  return (
    <label className="field">
      <span>{label}</span>
      {children}
      {hint && <small>{hint}</small>}
    </label>
  );
}
function Tag({ children, tone = "muted" }: any) {
  return <span className={"tag " + tone}>{children}</span>;
}
function Days({ value, onChange }: any) {
  return (
    <div className="days">
      {["L", "M", "M", "J", "V", "S", "D"].map((d, i) => (
        <button
          type="button"
          key={i}
          aria-label={
            [
              "Lunes",
              "Martes",
              "Miércoles",
              "Jueves",
              "Viernes",
              "Sábado",
              "Domingo",
            ][i]
          }
          aria-pressed={value.includes(i)}
          className={value.includes(i) ? "selected" : ""}
          onClick={() =>
            onChange(
              value.includes(i)
                ? value.filter((x: number) => x !== i)
                : [...value, i].sort(),
            )
          }
        >
          {d}
        </button>
      ))}
    </div>
  );
}
function Dialog({
  title,
  subtitle,
  children,
  onClose,
  onSave,
  saveLabel = "Guardar",
  wide = false,
}: any) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const dialogRef = useRef<HTMLElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement;
    const focusable = () =>
      Array.from(
        dialogRef.current?.querySelectorAll<HTMLElement>(
          "button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),a[href]",
        ) || [],
      );
    focusable()[0]?.focus();
    const old = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if (e.key === "Tab") {
        const items = focusable(),
          first = items[0],
          last = items.at(-1);
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last?.focus();
        }
        if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first?.focus();
        }
      }
    };
    window.addEventListener("keydown", key);
    return () => {
      document.body.style.overflow = old;
      window.removeEventListener("keydown", key);
      if (previous?.isConnected) previous.focus();
    };
  }, []);
  return (
    <div className="overlay">
      <section
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={"dialog " + (wide ? "wide" : "")}
      >
        <header>
          <div>
            <h2>{title}</h2>
            {subtitle && <p>{subtitle}</p>}
          </div>
          <button
            type="button"
            className="icon-btn"
            aria-label="Cerrar"
            onClick={onClose}
          >
            <X size={22} />
          </button>
        </header>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            if (!onSave) return;
            setBusy(true);
            setError("");
            try {
              await onSave();
            } catch (ex) {
              setError((ex as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <div className="dialog-content">
            {children}
            {error && (
              <div role="alert" className="notice danger">
                <AlertCircle size={18} />
                {error}
              </div>
            )}
          </div>
          {onSave && (
            <footer>
              <button
                type="button"
                className="button secondary"
                onClick={onClose}
              >
                Cancelar
              </button>
              <button className="button" disabled={busy}>
                {busy ? "Guardando…" : saveLabel}
                <Check size={17} />
              </button>
            </footer>
          )}
        </form>
      </section>
    </div>
  );
}
function Empty({ icon: Icon = Route, title, children, action }: any) {
  return (
    <div className="empty">
      <span className="empty-icon">
        <Icon size={30} />
      </span>
      <h3>{title}</h3>
      <p>{children}</p>
      {action}
    </div>
  );
}
function ListPager({ total, page, setPage }: any) {
  return (
    <div className="pager">
      <small>
        {total
          ? `${page * 10 + 1}–${Math.min(total, (page + 1) * 10)} de ${total}`
          : "Sin resultados"}
      </small>
      <div>
        <button
          className="icon-btn"
          disabled={page === 0}
          onClick={() => setPage(page - 1)}
          aria-label="Página anterior"
        >
          <ArrowLeft size={17} />
        </button>
        <button
          className="icon-btn"
          disabled={(page + 1) * 10 >= total}
          onClick={() => setPage(page + 1)}
          aria-label="Página siguiente"
        >
          <ArrowRight size={17} />
        </button>
      </div>
    </div>
  );
}

function MedicalVisitLink({ id, day, manage, preview, officeDemo=false }: any) {
  return manage ? (
    <button
      className="button small secondary"
      onClick={() => preview({ kind: "visitSummary", id })}
    >
      Ver seguimiento <ArrowRight size={14} />
    </button>
  ) : (
    <span className="actions"><a className="button small secondary" href={"/territorio/?report="+id}>Reporte</a><a
      className="button small"
      href={"/visitas/" + id + "?from=route&route_day=" + day}
    >
      Abrir visita <ArrowRight size={14} />
    </a></span>
  );
}

function App({onIdentity}:{onIdentity:(user:User|null)=>void}) {
  const [user, setUser] = useState<User | null>(null),
    [raw, setRaw] = useState<any>(null),
    [pending, setPending] = useState<Pending[]>([]),
    [boot, setBoot] = useState(true),
    [error, setError] = useState(""),
    [toast, setToast] = useState(""),
    [tab, setTab] = useState(new URLSearchParams(location.search).get('tab') || "route"),
    [toolsOpen, setToolsOpen] = useState(false),
    [rep, setRep] = useState(requestedRep),
    [day, setDay] = useState(
      requestedDay && /^\d{4}-\d{2}-\d{2}$/.test(requestedDay)
        ? requestedDay
        : today(),
    ),
    [query, setQuery] = useState(""),
    [filter, setFilter] = useState("all"),
    [page, setPage] = useState(0),
    [issuePage, setIssuePage] = useState(0),
    [modal, setModal] = useState<any>(null),
    [geometry, setGeometry] = useState<any>(null),
    [online, setOnline] = useState(navigator.onLine);
  useEffect(()=>{onIdentity(user)},[user]);
  const reload = async (current = user, chosen = rep) => {
    if (!current) return;
    try {
      await flush(current);
      const data = await readState(current, chosen || undefined);
      setRaw(data);
      setPending(
        await db.commands.where("actor_id").equals(current.id).toArray(),
      );
      setError("");
    } catch (e) {
      setError((e as Error).message);
      if (e instanceof ApiError && e.status === 401) {
        setUser(null);
        setRaw(null);
        setPending([]);
      }
    }
  };
  useEffect(() => {
    (async () => {
      try {
        const u = await session();
        setUser(u);
        if (!standaloneModule) await reload(u, requestedRep);
      } catch (e) {
        if (!(e instanceof ApiError) && cachedUser()) {
          const u = cachedUser()!;
          setUser(u);
          if (!standaloneModule) await reload(u, requestedRep);
        } else setError("");
      } finally {
        setBoot(false);
      }
    })();
  }, []);
  useEffect(() => {
    const update = () => setOnline(navigator.onLine);
    window.addEventListener("online", update);
    window.addEventListener("offline", update);
    return () => {
      window.removeEventListener("online", update);
      window.removeEventListener("offline", update);
    };
  }, []);
  useEffect(() => {
    if (!user || standaloneModule) return;
    reload();
    const t = setInterval(() => {
      if (document.visibilityState === "visible") reload();
    }, 20000);
    const refresh = () => {
      if (document.visibilityState === "visible") reload();
    };
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      clearInterval(t);
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, [user?.id, rep, online]);
  useEffect(() => {
    setPage(0);
    setQuery("");
    setFilter("all");
  }, [tab, rep]);
  useEffect(() => {
    if (toast) {
      const t = setTimeout(() => setToast(""), 6500);
      return () => clearTimeout(t);
    }
  }, [toast]);
  const s = useMemo(
    () => (raw ? optimistic(raw, pending) : null),
    [raw, pending],
  );
  const save = async (type: string, payload: any, version = 0) => {
    if (s?.can_edit === false) throw new Error("Tu perfil permite consultar el equipo. Los cambios de ruta corresponden a gerencia de línea o distrito.");
    const result = await send(user!, type, payload, version);
    await reload();
    setToast(
      result.queued
        ? "Guardado en este celular. Se enviará al recuperar conexión."
        : "Cambios guardados",
    );
    return result;
  };
  const plan = s?.plans.find(
    (p: any) =>
      p.day === day &&
      (p.status === "published" || (s.can_manage && p.status === "draft")),
  );
  useEffect(() => {
    setGeometry(null);
    setIssuePage(0);
    if (plan?.id)
      api("/routes/" + plan.id + "/geometry")
        .then((d) => setGeometry(d.geometry))
        .catch(() => {});
  }, [plan?.id]);
  if (boot)
    return (
      <main className="loading">
        <span className="logo">
          uno<span>·</span>
        </span>
        <p>Abriendo VisiMed…</p>
      </main>
    );
  if (!user)
    return (
      <Login
        onLogin={(u) => {
          setUser(u);
          reload(u, "");
        }}
      />
    );
  const workflowModule = new URLSearchParams(location.search).get("module");
  if (workflowModule === 'study') {
    const visit = new URLSearchParams(location.search).get('visit');
    return visit ? <BriefScreen user={user} id={visit}/> : <StudyScreen user={user}/>;
  }
  if (workflowModule === "calendar") return <CalendarScreen user={user}/>;
  if (workflowModule === "today") return <CalendarScreen user={user} todayOnly/>;
  if (workflowModule === "demo") return <DemoScreen user={user}/>;
  if (workflowModule === "marketing") return <MarketingScreen user={user}/>;
  if (workflowModule === "management") return <ManagementScreen user={user}/>;
  if (workflowModule === "tasks") return <TaskScreen user={user}/>;
  if (workflowModule === "library") return <LibraryScreen user={user}/>;
  if (workflowModule === "brief") return <BriefScreen user={user} id={new URLSearchParams(location.search).get("visit") || ""}/>;
  const voiceReportId = new URLSearchParams(location.search).get("report");
  if (voiceReportId) return <VoiceReport id={voiceReportId} user={user}/>;
  if (!s)
    return (
      <main className="loading">
        <h2>VisiMed</h2>
        <p>{error || "Cargando tu panel…"}</p>
        <button className="button" onClick={() => reload()}>
          Volver a intentar
        </button>
        <a href="/">Ir a Hoy</a>
      </main>
    );
  const site = (id: string) => s.sites.find((x: any) => x.id === id);
  const verification = (id: string) =>
    s.locations.find((x: any) => x.institution_id === id);
  const potential = (id: string, siteId?: string) =>
    s.potentials.find((x: any) => x.doctor_id === id && (!siteId || x.institution_id === siteId));
  const doctorContacts = (s.contacts?.length ? s.contacts.map((c: any) => ({
    ...s.doctors.find((d: any) => d.id === c.doctor_id),
    contact_id: c.id, institution_id: c.institution_id, contact: c,
  })) : s.doctors);
  const allDoctors = doctorContacts.filter(
    (d: any) =>
      (
        d.name +
        " " +
        (d.specialty || "") +
        " " +
        (site(d.institution_id)?.name || "") + " " + (site(d.institution_id)?.address || "")
      )
        .toLowerCase()
        .includes(query.toLowerCase()) &&
      (filter !== "missing" || !potential(d.id, d.institution_id)),
  );
  const allSites = s.sites.filter(
    (d: any) =>
      (d.name + " " + (d.address || ""))
        .toLowerCase()
        .includes(query.toLowerCase()) &&
      (filter !== "missing" || verification(d.id)?.status !== "verified"),
  );
  const allPharmacies = s.pharmacies.filter((d: any) =>
    (d.chain + " " + site(d.institution_id)?.name)
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  const requirementName = (r: any) =>
    r.doctor_id
      ? s.doctors.find((x: any) => x.id === r.doctor_id)?.name || "Médico"
      : site(
          s.pharmacies.find((x: any) => x.id === r.pharmacy_id)?.institution_id,
        )?.name || "Droguería";
  const allRequirements = s.requirements.filter((r: any) =>
    (requirementName(r) + " " + r.cycle_start + " " + r.cycle_end)
      .toLowerCase()
      .includes(query.toLowerCase()),
  );
  const verified = s.locations.filter(
    (x: any) => x.status === "verified",
  ).length;
  const latestJob = s.jobs.find((j: any) => j.day === day);
  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="/">
          <span className="logo">
            uno<span>·</span>
          </span>
          <span className="brand-divider" />
          <span>
            VisiMed <b>Novamed</b>
          </span>
        </a>
        <div className="top-actions">
          <span className={"connection " + (!online ? "offline" : "")}>
            {online ? <span className="live-dot" /> : <WifiOff size={15} />}
            <span>{online ? "Conectado" : "Sin conexión"}</span>
          </span>
          <a href="/" className="back-link">
            <ArrowLeft size={16} />
            <span>Ir a Hoy</span>
          </a>
          <span className="avatar" title={user.name}>
            {user.name
              .split(" ")
              .map((n) => n[0])
              .slice(0, 2)
              .join("")}
          </span>
        </div>
      </header>
      <div className="workspace">
        <aside className="sidebar">
          <div className="section-label">OPERACIÓN DE CAMPO</div>
          {[
            { key: "route", icon: Route, label: "Mi ruta" },
            { key: "panel", icon: Users, label: "Mi panel" },
            { key: "catalog", icon: BookOpen, label: "Catálogo SNC" },
            { key: "map", icon: MapPin, label: "Sedes y mapa" },
            { key: "potential", icon: Target, label: "Potencial médico" },
            { key: "pharmacy", icon: Store, label: "Droguerías" },
            ...(s.can_manage
              ? [
                  {
                    key: "planning",
                    icon: Settings2,
                    label: "Reglas de planeación",
                  },
                ]
              : []),
          ].filter((n) => s.can_edit !== false || ["route", "panel", "catalog"].includes(n.key)).map((n) => (
            <button
              key={n.key}
              className={(tab === n.key ? "nav-item active" : "nav-item") + (["map","catalog","planning"].includes(n.key)?" secondary-nav":"")}
              onClick={() => {setTab(n.key);setToolsOpen(false)}}
            >
              <n.icon size={19} />
              <span>{n.label}</span>
              <ChevronRight size={14} />
            </button>
          ))}
          <button className="nav-item mobile-more" aria-expanded={toolsOpen} aria-label="Más herramientas" onClick={()=>setToolsOpen(!toolsOpen)}><MoreHorizontal size={20}/><span>Más</span></button>
          {toolsOpen && <div className="mobile-tools"><strong>Herramientas</strong>{[{key:"catalog",label:"Catálogo SNC",icon:BookOpen},...(s.can_edit!==false?[{key:"map",label:"Sedes y mapa",icon:MapPin}]:[]),...(s.can_manage?[{key:"planning",label:"Reglas de planeación",icon:Settings2}]:[])].map(n=><button key={n.key} onClick={()=>{setTab(n.key);setToolsOpen(false)}}><n.icon size={20}/>{n.label}<ChevronRight size={16}/></button>)}</div>}
          <div className="side-foot">
            <span className="section-label">PILOTO SNC · BOGOTÁ</span>
            <p>
              Frecuencia primero.
              <br />
              Una jornada viable.
            </p>
            <small>Carro · Máximo habitual: 12 contactos</small>
          </div>
        </aside>
        <main className="main">
          <nav className="workflow-nav-links"><a href="/territorio/?module=calendar">Calendario unificado</a>{s.sites.some((x:any)=>x.name.includes('Demostración'))&&<a href="/territorio/?module=demo">Demo en Novamed</a>}</nav>
          <div className="page-intro">
            <div>
              <div className="eyebrow">SNC / BOGOTÁ</div>
              <h1>
                {
                  (
                    {
                      route: "Tu próxima parada, clara.",
                      panel: "Tu panel, sede por sede.",
                      catalog: "Productos y ciclo comercial.",
                      map: "Cada sede en su lugar.",
                      potential: "Conoce mejor tu panel.",
                      pharmacy: "Conecta la visita con el canal.",
                      planning: "Reglas que ordenan la jornada.",
                    } as any
                  )[tab]
                }
              </h1>
              <p>
                {
                  (
                    {
                      route:
                        "Una ruta preparada con horarios, frecuencia y tiempo real de trabajo.",
                      panel: "Médicos asignados, frecuencia del ciclo y horarios de recepción.",
                      catalog: "Consulta las marcas y presentaciones del archivo comercial SNC.",
                      map: "Verifica las direcciones que hacen posible una buena ruta.",
                      potential:
                        "Volumen y disponibilidad por médico y sede, con fuente y fecha.",
                      pharmacy:
                        "Visitas, disponibilidad y próximos pasos de cada punto de venta.",
                      planning:
                        "VisiMed construye el recorrido. Gerencia define las condiciones.",
                    } as any
                  )[tab]
                }
              </p>
            </div>
            {s.can_supervise && (
              <Field label="Visitador">
                <select
                  value={s.representative_id}
                  onChange={(e) => setRep(e.target.value)}
                >
                  {s.representatives.map((r: any) => (
                    <option key={r.id} value={r.id}>
                      {r.name}
                    </option>
                  ))}
                </select>
              </Field>
            )}
          </div>
          {s.user.management_profile && <div className="profile-bar">{({line:"Gerencia de línea",district:"Gerencia de distrito",training:"Gerencia de entrenamiento"} as any)[s.user.management_profile]} · Equipo SNC Bogotá{s.can_edit===false?" · Solo consulta":""}</div>}
          <nav className="workflow-nav-links" aria-label="Herramientas de seguimiento"><a href="/territorio/?module=marketing">Actividades de mercadeo</a>{s.user?.capabilities?.includes("dashboard.read")&&<a href="/territorio/?module=management">Dashboard de gerencia</a>}<a href={"/territorio/?module=tasks&rep="+s.representative_id}>Compromisos</a><a href="/territorio/?module=library">Biblioteca SNC</a></nav>
          {tab === "catalog" && <CatalogPanel data={s} day={day} />}
          {error && (
            <div className="notice danger">
              <AlertCircle size={18} />
              {error}
              <button className="text-button" onClick={() => reload()}>
                Reintentar
              </button>
            </div>
          )}
          {(pending.length > 0 || s.cached) && (
            <div className="notice">
              <WifiOff size={18} />
              <div>
                {pending.length
                  ? `${pending.length} cambio(s) guardados en este dispositivo`
                  : "Viendo la última información descargada"}
                {pending.find((x) => x.error) && (
                  <p>{pending.find((x) => x.error)?.error}</p>
                )}
              </div>
              <button
                className="text-button"
                onClick={() => setModal({ kind: "queue" })}
              >
                Revisar
              </button>
            </div>
          )}
          {tab === "route" && (
            <>
              {s.policy && (
                <section
                  className="origin-banner"
                  aria-label="Salida de la jornada"
                >
                  <span className="origin-icon">
                    <MapPin size={22} />
                  </span>
                  <div>
                    <span className="eyebrow">SALIDA DE LA JORNADA</span>
                    <h3>{s.policy.data.origin_label}</h3>
                    <p>
                      {s.policy.data.starts.slice(0, 5)}–
                      {s.policy.data.ends.slice(0, 5)} · Carro · Almuerzo{" "}
                      {s.policy.data.lunch_starts.slice(0, 5)}–
                      {s.policy.data.lunch_ends.slice(0, 5)}
                    </p>
                  </div>
                  <Tag tone={s.policy.active ? "green" : "amber"}>
                    {s.policy.active ? "Automática" : "Por activar"}
                  </Tag>
                </section>
              )}
              <div className="toolbar">
                <div className="date-control">
                  <CalendarDays size={18} />
                  <input
                    aria-label="Fecha de ruta"
                    type="date"
                    value={day}
                    onChange={(e) => setDay(e.target.value)}
                  />
                </div>
                <div className="toolbar-right">
                  {latestJob &&
                    ["queued", "running", "error"].includes(
                      latestJob.status,
                    ) && (
                      <Tag
                        tone={latestJob.status === "error" ? "amber" : "green"}
                      >
                        {prettyStatus[latestJob.status]}
                      </Tag>
                    )}
                  {s.can_manage && (
                    <button
                      className="button"
                      onClick={() => setModal({ kind: "generate" })}
                    >
                      <Route size={17} />
                      Calcular ruta
                    </button>
                  )}
                </div>
              </div>
              {latestJob?.error && (
                <div className="notice danger">
                  <AlertCircle size={18} />
                  {latestJob.error}
                </div>
              )}
              {plan ? (
                <>
                  <div className="route-summary">
                    <div>
                      <Tag
                        tone={plan.status === "published" ? "green" : "amber"}
                      >
                        {prettyStatus[plan.status]} · versión {plan.version}
                      </Tag>
                      <h2>
                        {plan.stops.length} contactos <span>en tu jornada</span>
                      </h2>
                      <p>{plan.stops.filter((x: any) => x.kind === "doctor").length} médicos · {plan.stops.filter((x: any) => x.kind === "pharmacy").length} droguerías</p>
                      <p>
                        <Clock size={15} />
                        {plan.metrics.travel_minutes} min de trayecto estimado{" "}
                        <span>·</span> Almuerzo{" "}
                        {plan.metrics.lunch
                          ?.map((x: string) => x.slice(0, 5))
                          .join("–") || "12:00–13:00"}
                      </p>
                    </div>
                    <div>
                      {s.can_manage && plan.status === "draft" && (
                        <button
                          className="button"
                          onClick={() => setModal({ kind: "publish", plan })}
                        >
                          Revisar y publicar
                          <ArrowRight size={16} />
                        </button>
                      )}
                      <small>Carro · Sin tráfico en vivo</small>
                    </div>
                  </div>
                  {plan.status === "published" && <ExecutionPanel user={user} plan={plan} day={day} canEdit={s.can_edit!==false} reload={reload}/>}
                  <div className="route-layout">
                    <section className="panel route-list">
                      <div className="panel-heading">
                        <h3>Recorrido del día</h3>
                        <Tag>
                          {plan.stops.filter((x: any) => x.locked).length}{" "}
                          iniciadas
                        </Tag>
                      </div>
                      {plan.stops.length ? (
                        plan.stops.map((stop: any, i: number) => (
                          <article className="stop" key={stop.key}>
                            <div
                              className={
                                "stop-number " +
                                (stop.kind === "pharmacy" ? "retail" : "")
                              }
                            >
                              {stop.locked ? <Check size={17} /> : i + 1}
                            </div>
                            <div className="stop-body">
                              <div className="stop-top">
                                <span className="stop-time">
                                  {localTime(
                                    stop.actual_arrived_at ||
                                      stop.scheduled_at ||
                                      stop.arrival_at,
                                  )}
                                </span>
                                <Tag
                                  tone={
                                    stop.kind === "pharmacy" ? "amber" : "muted"
                                  }
                                >
                                  {stop.kind === "pharmacy"
                                    ? "Droguería"
                                    : stop.kind === "marketing" ? "Mercadeo" : "Médico"}
                                </Tag>
                              </div>
                              <h3>{stop.label}</h3>
                              <p>{stop.reason}</p>
                              {stop.product_sequence?.length > 0 && (
                                <p className="muted">
                                  Secuencia:{" "}
                                  {stop.product_sequence
                                    .map(
                                      (id: string, index: number) =>
                                        `${index + 1}. ${s.products.find((p: any) => p.id === id)?.name || "Producto"}`,
                                    )
                                    .join(" · ")}
                                </p>
                              )}
                              <div className="stop-meta">
                                {stop.travel_minutes !== undefined && (
                                  <span>
                                    {stop.travel_minutes} min desde la parada
                                    anterior
                                  </span>
                                )}
                                {stop.status && (
                                  <span>
                                    {stop.rescheduled
                                      ? "Reprogramada en la agenda"
                                      : prettyStatus[stop.status] ||
                                        stop.status}
                                  </span>
                                )}
                              </div>
                              <div className="stop-actions">
                                <a
                                  className="button small secondary"
                                  href={`https://www.google.com/maps/dir/?api=1&destination=${stop.lat},${stop.lng}&travelmode=driving`}
                                  target="_blank"
                                  rel="noreferrer"
                                >
                                  <Navigation size={15} />
                                  Cómo llegar
                                </a>
                                {plan.status === "published" &&
                                  (stop.kind === "marketing" ? <a className="button small" href={"/territorio/?module=marketing&activity="+stop.target_id}>Abrir actividad <ArrowRight size={14}/></a> : stop.kind === "doctor" ? (
                                    <MedicalVisitLink
                                      id={stop.visit_id}
                                      officeDemo={day===today() && s.locations.some((geo:any)=>geo.institution_id===stop.institution_id && geo.source==="demo_setup")}
                                      day={day}
                                      manage={s.can_supervise}
                                      preview={setModal}
                                    />
                                  ) : (
                                    <button
                                      className="button small"
                                      onClick={() =>
                                        setModal({
                                          kind: "pharmacyDetail",
                                          item: s.pharmacies.find(
                                            (p: any) => p.id === stop.target_id,
                                          ),
                                        })
                                      }
                                    >
                                      Abrir visita
                                      <ArrowRight size={14} />
                                    </button>
                                  ))}
                              </div>
                            </div>
                          </article>
                        ))
                      ) : (
                        <Empty title="Sin paradas asignadas">
                          Revisa los motivos y completa los datos que faltan.
                        </Empty>
                      )}
                    </section>
                    <section className="panel route-map">
                      <TerritoryMap
                        points={[
                          ...(plan.metrics.origin
                            ? [
                                {
                                  ...plan.metrics.origin,
                                  kind: "origin",
                                  label: "Salida del recorrido",
                                  position: "S",
                                },
                              ]
                            : []),
                          ...plan.stops.map((x: any, i: number) => ({
                            ...x,
                            position: i + 1,
                          })),
                        ]}
                        geometry={geometry}
                      />
                      <div className="map-caption">
                        <span className="legend-dot" />
                        Médico
                        <span className="legend-dot retail" />
                        Droguería
                        <span className="map-note">
                          Tiempos estimados sobre red vial
                        </span>
                      </div>
                    </section>
                  </div>
                  {plan.issues.length > 0 && (
                    <section className="panel issues">
                      <div className="panel-heading">
                        <h3>Pendientes de planeación</h3>
                        <Tag tone="amber">{plan.issues.length}</Tag>
                      </div>
                      {plan.issues
                        .slice(issuePage * 10, issuePage * 10 + 10)
                        .map((x: any, i: number) => (
                          <div className="issue-row" key={i}>
                            <AlertCircle size={16} />
                            <span>
                              <b>{x.label || "Contacto"}</b>
                              {x.reason}
                            </span>
                          </div>
                        ))}
                      <ListPager
                        total={plan.issues.length}
                        page={issuePage}
                        setPage={setIssuePage}
                      />
                    </section>
                  )}
                </>
              ) : (
                <section className="panel">
                  <Empty
                    title="La ruta empieza con un territorio listo."
                    action={
                      <button
                        className="button secondary"
                        onClick={() => setTab("map")}
                      >
                        Revisar mis sedes
                        <ArrowRight size={16} />
                      </button>
                    }
                  >
                    {s.doctors.length === 0 && s.pharmacies.length === 0
                      ? "Esta cuenta todavía no tiene un panel asignado. Gerencia debe vincular sus médicos y droguerías antes de generar recorridos reales."
                      : "El motor usa las sedes verificadas, los horarios de recepción y la frecuencia aprobada. Las citas existentes también se incorporan al recorrido."}
                  </Empty>
                  <div className="readiness">
                    <div>
                      <strong>
                        {verified}/{s.sites.length}
                      </strong>
                      <span>Sedes verificadas</span>
                    </div>
                    <div>
                      <strong>
                        {(s.availability || []).length}/{(s.contacts || s.doctors).length}
                      </strong>
                      <span>Horarios documentados</span>
                    </div>
                    <div>
                      <strong>
                        {s.requirements.filter((x: any) => x.active).length}
                      </strong>
                      <span>Reglas de frecuencia</span>
                    </div>
                    <div>
                      <strong>
                        {s.policy?.active ? "Activa" : "Pendiente"}
                      </strong>
                      <span>Planeación automática</span>
                    </div>
                  </div>
                </section>
              )}
              {(s.agenda || []).some(
                (v: any) =>
                  dateKey(v.scheduled_at) === day &&
                  !plan?.stops.some((x: any) => x.visit_id === v.id),
              ) && (
                <section className="panel connected-agenda">
                  <div className="panel-heading">
                    <h3>También en tu agenda</h3>
                    <Tag>VisiMed</Tag>
                  </div>
                  <p className="muted">
                    Son las mismas visitas de la app. Las citas manuales
                    conservan su horario cuando se recalcula la ruta.
                  </p>
                  {(s.agenda || [])
                    .filter(
                      (v: any) =>
                        dateKey(v.scheduled_at) === day &&
                        !plan?.stops.some((x: any) => x.visit_id === v.id),
                    )
                    .map((v: any) => (
                      <div className="agenda-entry" key={v.id}>
                        <span className="stop-time">
                          {localTime(v.scheduled_at)}
                        </span>
                        <div>
                          <strong>{v.label}</strong>
                          <p>
                            {v.kind === "doctor" ? "Médico" : v.kind === "marketing" ? "Mercadeo" : "Droguería"} ·{" "}
                            {prettyStatus[v.status] || v.status}
                          </p>
                        </div>
                        {v.kind === "marketing" ? <a className="button small" href={v.href}>Abrir actividad</a> : v.kind === "doctor" ? (
                          <MedicalVisitLink
                            id={v.id}
                            day={day}
                            manage={s.can_supervise}
                            preview={setModal}
                          />
                        ) : (
                          <button
                            className="button small secondary"
                            onClick={() =>
                              setModal({
                                kind: "pharmacyDetail",
                                item: s.pharmacies.find(
                                  (p: any) => p.id === v.target_id,
                                ),
                              })
                            }
                          >
                            Abrir <ArrowRight size={14} />
                          </button>
                        )}
                      </div>
                    ))}
                </section>
              )}
            </>
          )}
          {tab === "panel" && (
            <>
              <div className="toolbar"><SearchBox value={query} change={(q: string) => {setQuery(q); setPage(0);}} /></div>
              <section className="panel">
                <div className="panel-heading"><h3>{s.doctors.length} médicos · {doctorContacts.length} contactos</h3><span className="muted">Panel SNC</span></div>
                {allDoctors.slice(page*10,page*10+10).map((d: any) => {
                  const place=site(d.institution_id);
                  const hours=(s.availability || []).find((a:any)=>a.doctor_id===d.id && a.institution_id===d.institution_id);
                  return <div className="list-item" key={d.contact_id || d.id}>
                    <span className="item-main"><b>{d.name}</b><small>{d.specialty} · {place?.city}</small><small>{place?.address}</small>
                      <div className="contact-tags">
                        <Tag tone={verification(d.institution_id)?.status==="verified"?"green":"amber"}>{verification(d.institution_id)?.status==="verified"?"Dirección validada":"Revisar dirección"}</Tag>
                        <Tag tone={hours?"green":"amber"}>{hours?`${hours.data.reception.opens.slice(0,5)}–${hours.data.reception.closes.slice(0,5)}`:"Horario pendiente"}</Tag>
                        {d.contact?.data.fz && <Tag tone="muted">FZ {d.contact.data.fz} / ciclo</Tag>}
                        {hours?.data.appointment_required && <Tag tone="amber">Requiere cita</Tag>}
                        {d.contact && !d.contact.active && <Tag tone="muted">Fuera del piloto presencial Bogotá</Tag>}
                      </div>
                      {s.can_edit !== false && <div className="contact-actions"><button className="text-button" onClick={()=>setModal({kind:"availability",doctor:d})}>Confirmar horario</button><button className="text-button" onClick={()=>setModal({kind:"location",site:place})}>Ver ubicación</button></div>}
                    </span>
                  </div>;
                })}
                <ListPager total={allDoctors.length} page={page} setPage={setPage}/>
              </section>
            </>
          )}
          {tab === "map" && (
            <>
              <div className="toolbar">
                <SearchBox
                  value={query}
                  change={(q: string) => {
                    setQuery(q);
                    setPage(0);
                  }}
                />
                <select
                  aria-label="Filtrar sedes"
                  value={filter}
                  onChange={(e) => {
                    setFilter(e.target.value);
                    setPage(0);
                  }}
                >
                  <option value="all">Todas las sedes</option>
                  <option value="missing">Por verificar</option>
                </select>
              </div>
              <div className="map-layout">
                <section className="panel">
                  <div className="panel-heading">
                    <h3>Sedes del territorio</h3>
                    <Tag tone="green">{verified} verificadas</Tag>
                  </div>
                  {allSites.slice(page * 10, page * 10 + 10).map((x: any) => (
                    <button
                      className="list-item"
                      key={x.id}
                      onClick={() => setModal({ kind: "location", site: x })}
                    >
                      <span className="item-icon">
                        <MapPin size={20} />
                      </span>
                      <span className="item-main">
                        <b>{x.name}</b>
                        <small>
                          {x.address || "Dirección pendiente"} ·{" "}
                          {x.city || "Ciudad pendiente"}
                        </small>
                        <Tag
                          tone={
                            verification(x.id)?.status === "verified"
                              ? "green"
                              : "amber"
                          }
                        >
                          {verification(x.id)?.status === "verified"
                            ? "Ubicación verificada"
                            : "Revisar ubicación"}
                        </Tag>
                      </span>
                      <ChevronRight size={17} />
                    </button>
                  ))}
                  <ListPager
                    total={allSites.length}
                    page={page}
                    setPage={setPage}
                  />
                </section>
                <section className="panel map-full">
                  <TerritoryMap
                    points={s.sites.filter(
                      (x: any) => verification(x.id)?.status === "verified",
                    )}
                  />
                  <div className="map-caption">
                    Solo se dibujan ubicaciones verificadas. No se inventan
                    puntos.
                  </div>
                </section>
              </div>
            </>
          )}
          {tab === "potential" && (
            <>
              <PotentialInsights potentials={s.potentials} doctors={s.doctors}/>
              <div className="toolbar">
                <SearchBox
                  value={query}
                  change={(q: string) => {
                    setQuery(q);
                    setPage(0);
                  }}
                />
                <select
                  aria-label="Filtrar potencial"
                  value={filter}
                  onChange={(e) => {
                    setFilter(e.target.value);
                    setPage(0);
                  }}
                >
                  <option value="all">Todo el panel</option>
                  <option value="missing">Sin perfil</option>
                </select>
              </div>
              <section className="panel">
                <div className="panel-heading">
                  <h3>Médico y sede</h3>
                  <span className="muted">
                    {s.potentials.length} perfiles completos
                  </span>
                </div>
                {allDoctors.slice(page * 10, page * 10 + 10).map((d: any) => {
                  const p = potential(d.id, d.institution_id);
                  return (
                    <button
                      className="list-item"
                      key={d.contact_id || d.id}
                      onClick={() =>
                        d.institution_id
                          ? setModal({ kind: "potential", doctor: d })
                          : setToast(
                              "Este médico necesita una sede asignada en el panel",
                            )
                      }
                    >
                      <span className="item-icon">
                        <Users size={20} />
                      </span>
                      <span className="item-main">
                        <b>{d.name}</b>
                        <small>
                          {d.specialty || "Especialidad pendiente"} ·{" "}
                          {site(d.institution_id)?.name || "Sin sede"}
                        </small>
                        <Tag
                          tone={
                            !p ? "amber" : p.summary.stale ? "amber" : "green"
                          }
                        >
                          {!p
                            ? "Completar potencial"
                            : p.summary.stale
                              ? "Actualizar perfil"
                              : `${p.summary.weekly_consultations} atenciones estimadas/semana`}
                        </Tag>
                      </span>
                      <ChevronRight size={17} />
                    </button>
                  );
                })}
                <ListPager
                  total={allDoctors.length}
                  page={page}
                  setPage={setPage}
                />
              </section>
              <div className="footnote">
                El potencial es una estimación documentada. No representa
                intención de prescripción ni valor económico del médico.
              </div>
            </>
          )}
          {tab === "pharmacy" && (
            <>
              <div className="toolbar">
                <SearchBox
                  value={query}
                  change={(q: string) => {
                    setQuery(q);
                    setPage(0);
                  }}
                />
                <button
                  className="button"
                  onClick={() => setModal({ kind: "pharmacy" })}
                >
                  <Plus size={17} />
                  Nueva droguería
                </button>
              </div>
              <section className="panel">
                {allPharmacies.length ? (
                  allPharmacies
                    .slice(page * 10, page * 10 + 10)
                    .map((p: any) => (
                      <button
                        key={p.id}
                        className="list-item"
                        onClick={() =>
                          setModal({ kind: "pharmacyDetail", item: p })
                        }
                      >
                        <span className="item-icon retail">
                          <Store size={21} />
                        </span>
                        <span className="item-main">
                          <b>{site(p.institution_id)?.name}</b>
                          <small>
                            {p.chain} · {site(p.institution_id)?.address}
                          </small>
                          <Tag
                            tone={
                              verification(p.institution_id)?.status ===
                              "verified"
                                ? "green"
                                : "amber"
                            }
                          >
                            {verification(p.institution_id)?.status ===
                            "verified"
                              ? "Sede verificada"
                              : "Ubicación pendiente"}
                          </Tag>
                          <Tag>
                            {
                              s.pharmacy_visits.filter(
                                (v: any) => v.pharmacy_id === p.id,
                              ).length
                            }{" "}
                            visitas
                          </Tag>
                        </span>
                        <ChevronRight size={18} />
                      </button>
                    ))
                ) : (
                  <Empty
                    icon={Store}
                    title="El canal también tiene una ruta."
                    action={
                      <button
                        className="button"
                        onClick={() => setModal({ kind: "pharmacy" })}
                      >
                        <Plus size={16} />
                        Registrar primera droguería
                      </button>
                    }
                  >
                    Agrega las sedes que realmente visitas para documentar
                    disponibilidad, resultados y seguimiento.
                  </Empty>
                )}
                <ListPager
                  total={allPharmacies.length}
                  page={page}
                  setPage={setPage}
                />
              </section>
            </>
          )}
          {tab === "planning" && (
            <>
              <section className="panel policy-card">
                <div>
                  <Tag tone={s.policy?.active ? "green" : "amber"}>
                    {s.policy?.active
                      ? "Planeación automática activa"
                      : "Configuración pendiente"}
                  </Tag>
                  <h2>Una política por visitador</h2>
                  <p>
                    Jornada, origen y publicación. La excepción de capacidad se
                    aprueba por versión de ruta.
                  </p>
                  <p>
                    Objetivo diario: 5–10 médicos y 2–5 droguerías, con 12
                    contactos como máximo habitual.
                  </p>
                  {s.policy && (
                    <p>
                      <b>
                        {s.policy.data.starts.slice(0, 5)}–
                        {s.policy.data.ends.slice(0, 5)}
                      </b>{" "}
                      · {s.policy.data.origin_label} · Carro
                    </p>
                  )}
                </div>
                <button
                  className="button"
                  onClick={() => setModal({ kind: "policy" })}
                >
                  <Settings2 size={17} />
                  {s.policy ? "Editar política" : "Configurar política"}
                </button>
              </section>
              <div className="toolbar">
                <h2>Frecuencia y secuencia</h2>
                <button
                  className="button secondary"
                  onClick={() => setModal({ kind: "requirement" })}
                >
                  <Plus size={17} />
                  Agregar regla
                </button>
              </div>
              <SearchBox
                value={query}
                change={(q: string) => {
                  setQuery(q);
                  setPage(0);
                }}
              />
              <section className="panel">
                {allRequirements.length ? (
                  allRequirements
                    .slice(page * 10, page * 10 + 10)
                    .map((r: any) => (
                      <button
                        className="list-item"
                        key={r.id}
                        onClick={() =>
                          setModal({ kind: "requirement", item: r })
                        }
                      >
                        <span className="item-icon">
                          <CalendarDays size={20} />
                        </span>
                        <span className="item-main">
                          <b>{requirementName(r)}</b>
                          <small>
                            {r.cycle_start} → {r.cycle_end} ·{" "}
                            {r.data.windows.length} impactos · separación{" "}
                            {r.data.min_gap_days} días
                          </small>
                          <Tag tone={r.active ? "green" : "muted"}>
                            {r.active ? "Activa" : "Inactiva"}
                          </Tag>
                        </span>
                        <ChevronRight size={18} />
                      </button>
                    ))
                ) : (
                  <Empty
                    title="Define qué contactos son exigibles."
                    icon={CalendarDays}
                  >
                    Cada regla conserva las ventanas del ciclo y la secuencia de
                    productos. El sistema no deduce la frecuencia del número de
                    filas.
                  </Empty>
                )}
                <ListPager
                  total={allRequirements.length}
                  page={page}
                  setPage={setPage}
                />
              </section>
            </>
          )}
        </main>
      </div>
      {toast && (
        <div role="status" className="toast">
          <CheckCircle2 size={19} />
          <span>{toast}</span>
          <button
            className="icon-btn"
            onClick={() => setToast("")}
            aria-label="Cerrar mensaje"
          >
            <X size={17} />
          </button>
        </div>
      )}
      {modal?.kind === "availability" && <AvailabilityEditor doctor={modal.doctor} site={site(modal.doctor.institution_id)} existing={(s.availability || []).find((a:any)=>a.doctor_id===modal.doctor.id && a.institution_id===modal.doctor.institution_id)} save={save} close={()=>setModal(null)}/>}
      {modal?.kind === "visitSummary" &&
        (() => {
          const visit = s.visits.find((v: any) => v.id === modal.id);
          const doctor = s.doctors.find((d: any) => d.id === visit?.doctor_id);
          return (
            <Dialog
              title="Seguimiento de visita"
              subtitle={doctor?.name || "Visita médica"}
              onClose={() => setModal(null)}
            >
              <div className="form-section">
                <Tag tone="green">
                  {prettyStatus[visit?.status] || visit?.status}
                </Tag>
                {visit && (
                  <p>
                    {dateLabel(visit.scheduled_at)} ·{" "}
                    {localTime(visit.scheduled_at)}
                  </p>
                )}
                <p>{site(doctor?.institution_id)?.name}</p>
                <p className="muted">
                  Estado de la visita en VisiMed. El visitador registra la
                  llegada, la salida y su reporte desde su propia cuenta.
                </p>
              </div>
            </Dialog>
          );
        })()}
      {modal?.kind === "location" && (
        <LocationEditor
          site={modal.site}
          existing={verification(modal.site.id)}
          save={save}
          close={() => setModal(null)}
        />
      )}
      {modal?.kind === "potential" && (
        <PotentialEditor
          doctor={modal.doctor}
          existing={potential(modal.doctor.id, modal.doctor.institution_id)}
          site={site(modal.doctor.institution_id)}
          save={save}
          close={() => setModal(null)}
        />
      )}
      {modal?.kind === "pharmacy" && (
        <PharmacyEditor
          existing={modal.item}
          site={site(modal.item?.institution_id)}
          rep={s.representative_id}
          save={save}
          close={() => setModal(null)}
        />
      )}
      {modal?.kind === "pharmacyDetail" && (
        <PharmacyDetail
          item={
            s.pharmacies.find((x: any) => x.id === modal.item.id) || modal.item
          }
          state={s}
          save={save}
          open={setModal}
          close={() => setModal(null)}
        />
      )}
      {modal?.kind === "schedule" && (
        <ScheduleEditor
          item={modal.item}
          save={save}
          close={() => setModal(null)}
        />
      )}
      {modal?.kind === "report" && (
        <ReportEditor
          visit={modal.visit}
          products={s.products}
          save={save}
          close={() => setModal(null)}
        />
      )}
      {modal?.kind === "referral" && (
        <ReferralEditor
          pharmacy={modal.item}
          state={s}
          save={save}
          close={() => setModal(null)}
        />
      )}
      {modal?.kind === "policy" && (
        <PolicyEditor
          existing={s.policy}
          rep={s.representative_id}
          save={save}
          close={() => setModal(null)}
        />
      )}
      {modal?.kind === "requirement" && (
        <RequirementEditor
          existing={modal.item}
          state={s}
          save={save}
          close={() => setModal(null)}
        />
      )}
      {modal?.kind === "generate" && (
        <GenerateEditor
          day={day}
          rep={s.representative_id}
          save={save}
          close={() => setModal(null)}
        />
      )}
      {modal?.kind === "publish" && (
        <PublishEditor
          plan={modal.plan}
          save={save}
          close={() => setModal(null)}
        />
      )}
      {modal?.kind === "queue" && (
        <Dialog
          title="Cambios del dispositivo"
          subtitle="Se enviarán en orden cuando haya conexión."
          onClose={() => setModal(null)}
        >
          {pending.map((p) => (
            <div className="queue-item" key={p.id}>
              <h4>{labels[p.type] || "Cambio de territorio"}</h4>
              <p>{p.error || "Pendiente de sincronizar"}</p>
              {p.error && (
                <button
                  className="text-button danger-text"
                  onClick={async () => {
                    await db.commands.delete(p.id);
                    await reload();
                  }}
                >
                  Descartar este cambio local
                </button>
              )}
            </div>
          ))}
          {!pending.length && <p>No hay cambios pendientes.</p>}
        </Dialog>
      )}
    </div>
  );
}

function AvailabilityEditor({ doctor, site, existing, save, close }: any) {
  const [slots,setSlots]=useState<any[]>(existing ? [existing.data.reception,...(existing.data.additional_reception || [])] : [{weekdays:[],opens:"",closes:""}]);
  const [appointment,setAppointment]=useState(existing?.data.appointment_required || false);
  const [source,setSource]=useState(existing?.data.source || "representative");
  const [observed,setObserved]=useState(existing?.data.observed_on || today());
  const [notes,setNotes]=useState(existing?.data.notes || "");
  const edit=(index:number,key:string,value:any)=>setSlots(slots.map((slot,i)=>i===index?{...slot,[key]:value}:slot));
  return <Dialog title="Confirmar horario de recepción" subtitle={`${doctor.name} · ${site?.address || site?.name}`} onClose={close} onSave={async()=>{
    if(slots.some(r=>!r.weekdays.length || !r.opens || !r.closes)) throw new Error("Completa los días y horas de cada franja.");
    await save("availability.save",{doctor_id:doctor.id,institution_id:doctor.institution_id,reception:slots[0],additional_reception:slots.slice(1),appointment_required:appointment,source,observed_on:observed,notes},existing?.version || 0);close();
  }}>
    <p className="muted">Registra cuándo recibe al visitador. Las franjas separadas conservan los periodos en que la sede no atiende.</p>
    {slots.map((slot,index)=><div className="form-section" key={index}>
      <h3>Franja {index+1}</h3><Days value={slot.weekdays} onChange={(v:any)=>edit(index,"weekdays",v)}/>
      <div className="form-grid"><Field label="Desde"><input type="time" required value={slot.opens} onChange={e=>edit(index,"opens",e.target.value)}/></Field><Field label="Hasta"><input type="time" required value={slot.closes} onChange={e=>edit(index,"closes",e.target.value)}/></Field></div>
      {index>0 && <button type="button" className="text-button" onClick={()=>setSlots(slots.filter((_,i)=>i!==index))}>Quitar franja</button>}
    </div>)}
    {slots.length<7 && <button type="button" className="secondary" onClick={()=>setSlots([...slots,{weekdays:[],opens:"",closes:""}])}>Añadir franja</button>}
    <div className="form-grid"><Field label="Fuente"><select value={source} onChange={e=>setSource(e.target.value)}><option value="representative">Confirmado por el visitador</option><option value="doctor">Confirmado por el médico / sede</option><option value="document">Documento / Pharmadvisor</option></select></Field><Field label="Fecha de confirmación"><input type="date" max={today()} required value={observed} onChange={e=>setObserved(e.target.value)}/></Field></div>
    <label className="checkbox"><input type="checkbox" checked={appointment} onChange={e=>setAppointment(e.target.checked)}/>Requiere una cita previamente acordada</label>
    <Field label="Observaciones"><textarea maxLength={1000} value={notes} onChange={e=>setNotes(e.target.value)}/></Field>
  </Dialog>;
}

function SearchBox({ value, change }: any) {
  return (
    <div className="search">
      <Search size={17} />
      <input
        aria-label="Buscar"
        placeholder="Buscar por nombre o sede…"
        value={value}
        onChange={(e) => change(e.target.value)}
      />
    </div>
  );
}
function Login({ onLogin }: any) {
  const [phone, setPhone] = useState(""),
    [pin, setPin] = useState(""),
    [error, setError] = useState("");
  return (
    <main className="login">
      <div className="login-card">
        <span className="logo">
          uno<span>·</span>
        </span>
        <div className="eyebrow">VISIMED · TERRITORIO</div>
        <h1>Tu jornada comienza aquí.</h1>
        <p>Usa tu cuenta de VisiMed para abrir rutas, sedes y droguerías.</p>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            try {
              onLogin(await login(phone, pin));
            } catch (ex) {
              setError((ex as Error).message);
            }
          }}
        >
          <Field label="Celular">
            <input
              value={phone}
              onChange={(e) => setPhone(e.target.value)}
              type="tel"
              required
              autoComplete="username"
            />
          </Field>
          <Field label="PIN de acceso">
            <input
              value={pin}
              onChange={(e) => setPin(e.target.value)}
              type="password"
              inputMode="numeric"
              minLength={6}
              maxLength={6}
              required
              autoComplete="current-password"
            />
          </Field>
          {error && (
            <p className="danger-text" role="alert">
              {error}
            </p>
          )}
          <button className="button">
            Entrar
            <ArrowRight size={17} />
          </button>
        </form>
        <a className="back-link" href="/">
          <ArrowLeft size={15} />
          Ir a Hoy
        </a>
      </div>
    </main>
  );
}

function LocationEditor({ site, existing, save, close }: any) {
  const [point, setPoint] = useState<any>(
      Number.isFinite(site.lat) && Number.isFinite(site.lng)
        ? { lat: site.lat, lng: site.lng }
        : undefined,
    ),
    [source, setSource] = useState("map"),
    [query, setQuery] = useState(
      [site.address, site.city, "Colombia"].filter(Boolean).join(", "),
    ),
    [candidates, setCandidates] = useState<any[]>([]),
    [finding, setFinding] = useState(false),
    [message, setMessage] = useState(""),
    [confirmed, setConfirmed] = useState(false);
  return (
    <Dialog
      title="Verificar ubicación"
      subtitle={site.name}
      onClose={close}
      wide
      onSave={async () => {
        if (!point || !confirmed)
          throw new Error(
            "Selecciona el punto y confirma que corresponde a esta sede",
          );
        await save(
          "location.verify",
          {
            institution_id: site.id,
            lat: point.lat,
            lng: point.lng,
            source,
            accuracy_m: point.accuracy_m || null,
            note: site.address || "",
            confirmed: true,
          },
          existing?.version || 0,
        );
        close();
      }}
      saveLabel="Guardar ubicación verificada"
    >
      <p className="address-line">
        <MapPin size={16} />
        {site.address} · {site.city}
      </p>
      <div className="search-action">
        <input
          aria-label="Dirección para buscar"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <button
          type="button"
          className="button secondary"
          disabled={finding}
          onClick={async () => {
            setFinding(true);
            setMessage("");
            try {
              const r = await api("/geocode?q=" + encodeURIComponent(query));
              setCandidates(r.candidates);
              if (!r.candidates.length)
                setMessage(
                  "No hubo coincidencias. Selecciona el punto en el mapa.",
                );
            } catch (e) {
              setMessage((e as Error).message);
            } finally {
              setFinding(false);
            }
          }}
        >
          {finding ? "Buscando…" : "Buscar"}
        </button>
      </div>
      {candidates.map((c, i) => (
        <button
          type="button"
          className="candidate"
          key={i}
          onClick={() => {
            setPoint(c);
            setSource("geocoder");
            setConfirmed(false);
            setCandidates([]);
          }}
        >
          <MapPin size={16} />
          {c.label}
          <ChevronRight size={15} />
        </button>
      ))}
      {message && <div className="notice">{message}</div>}
      <TerritoryMap
        selected={point}
        onSelect={(p) => {
          setPoint(p);
          setSource("map");
          setConfirmed(false);
        }}
      />
      <div className="coordinates">
        <span>
          {point
            ? `${point.lat.toFixed(6)}, ${point.lng.toFixed(6)}`
            : "Toca el mapa sobre la entrada de la sede"}
        </span>
        <button
          type="button"
          className="text-button"
          onClick={async () => {
            try {
              setPoint(await locate());
              setSource("gps");
              setConfirmed(false);
            } catch (e) {
              setMessage((e as Error).message);
            }
          }}
        >
          <LocateFixed size={16} />
          Estoy en la sede
        </button>
      </div>
      <label className="checkbox">
        <input
          type="checkbox"
          checked={confirmed}
          onChange={(e) => setConfirmed(e.target.checked)}
        />
        <span>
          Confirmo que el punto corresponde a esta sede y su entrada de acceso.
        </span>
      </label>
      <small className="muted">
        Una coincidencia del buscador es una propuesta. La ubicación se usa para
        planear el recorrido cuando la verificas.
      </small>
    </Dialog>
  );
}

function PotentialEditor({ doctor, existing, site, save, close }: any) {
  const [step,setStep] = useState(0);
  const [f, set] = useState<any>(
    existing?.data
      ? structuredClone(existing.data)
      : {
          practice_days: [],
          patients_per_day: "",
          consultations: {
            eps: 0,
            private: 0,
            prepaid: 0,
            complementary: 0,
            unknown: 0,
          },
          reception: null,
          appointment_required: false,
          appointment_notice_days: 0,
          snc_percentage: null,
          source: "representative",
          observed_on: today(),
          notes: "",
        },
  );
  const change = (key: string, value: any) =>
    set((p: any) => ({ ...p, [key]: value }));
  const total = Object.values(f.consultations).reduce(
    (a: number, b: number) => a + b,
    0,
  ) as number;
  return (
    <Dialog
      title="Conocer el potencial del médico"
      subtitle={doctor.name + " · " + site?.name}
      onClose={close}
      wide
      saveLabel={step<2?'Continuar':'Guardar cuestionario'}
      onSave={async () => {
        if(step===0&&(!f.practice_days.length||f.patients_per_day===''||total!==Number(f.patients_per_day))) throw new Error('Selecciona los días y revisa que las modalidades sumen el total diario. Usa «No informado» para lo que no conozcas.');
        if(step<2){setStep(step+1);return;}
        await save(
          "potential.save",
          { ...f, doctor_id: doctor.id, institution_id: doctor.institution_id },
          existing?.version || 0,
        );
        close();
      }}
    >
      <PotentialMix data={f}/><div className="actions">{['1. Consulta','2. Recepción','3. Revisar'].map((label,i)=><button key={label} type="button" className="text-button" disabled={i>step} onClick={()=>setStep(i)} aria-current={i===step?'step':undefined}>{label}</button>)}</div>
      {step===0&&<div className="form-section">
        <h3>¿Cuántos pacientes atiende en esta sede?</h3>
        <Field label="¿Qué días de la semana trabaja aquí?">
          <Days
            value={f.practice_days}
            onChange={(v: any) => change("practice_days", v)}
          />
        </Field>
        <div className="form-grid">
          <Field label="¿Cuántos pacientes atiende en un día habitual?">
            <input
              type="number"
              min="0"
              max="1000"
              required
              value={f.patients_per_day}
              onChange={(e) =>
                change("patients_per_day", Number(e.target.value))
              }
            />
          </Field>
          <Field
            label="Proporción relacionada con SNC (%)"
            hint="Déjalo vacío si no se conoce."
          >
            <input
              type="number"
              min="0"
              max="100"
              step="0.1"
              value={f.snc_percentage ?? ""}
              onChange={(e) =>
                change(
                  "snc_percentage",
                  e.target.value === "" ? null : Number(e.target.value),
                )
              }
            />
          </Field>
        </div>
        <h4>De ese total, ¿cuántos corresponden a cada tipo de consulta?</h4>
        <p className="muted">Son cantidades de pacientes del mismo día, no porcentajes. No es necesario conocer nombres ni historias clínicas.</p>
        <div className="mix-grid">
          {[
            ["eps", "EPS"],
            ["private", "Particular"],
            ["prepaid", "Prepagada"],
            ["complementary", "Complementario"],
            ["unknown", "No informado"],
          ].map(([k, label]) => (
            <Field label={label} key={k}>
              <input
                type="number"
                min="0"
                required
                value={f.consultations[k]}
                onChange={(e) =>
                  change("consultations", {
                    ...f.consultations,
                    [k]: Number(e.target.value),
                  })
                }
              />
            </Field>
          ))}
        </div>
        <button className="text-button" type="button" onClick={()=>change('consultations',{...f.consultations,unknown:Math.max(0,Number(f.patients_per_day)-Number(f.consultations.eps)-Number(f.consultations.private)-Number(f.consultations.prepaid)-Number(f.consultations.complementary))})}>Asignar lo que falta a «No informado»</button>
        <div
          className={
            "total " + (total === f.patients_per_day ? "valid" : "invalid")
          }
        >
          Total: {total} / {f.patients_per_day} pacientes{" "}
          {total === f.patients_per_day ? (
            <Check size={16} />
          ) : (
            <AlertCircle size={16} />
          )}
        </div>
      </div>}
      {step===1&&<div className="form-section">
        <h3>¿Ya confirmaste cuándo recibe visitadores?</h3>
        <p className="muted">El horario de consulta no equivale al horario de visita comercial. Puedes guardar el potencial sin conocer este dato.</p>
        <label className="checkbox"><input type="checkbox" checked={!!f.reception} onChange={e=>change('reception',e.target.checked?{weekdays:[],opens:'',closes:''}:null)}/>Sí, tengo el horario de recepción confirmado.</label>
        {f.reception&&<>
        <Field label="Días en que recibe visita comercial">
          <Days
            value={f.reception.weekdays}
            onChange={(v: any) =>
              change("reception", { ...f.reception, weekdays: v })
            }
          />
        </Field>
        <div className="form-grid">
          <Field label="Desde">
            <input
              type="time"
              required
              value={f.reception.opens}
              onChange={(e) =>
                change("reception", { ...f.reception, opens: e.target.value })
              }
            />
          </Field>
          <Field label="Hasta">
            <input
              type="time"
              required
              value={f.reception.closes}
              onChange={(e) =>
                change("reception", { ...f.reception, closes: e.target.value })
              }
            />
          </Field>
        </div>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={f.appointment_required}
            onChange={(e) => change("appointment_required", e.target.checked)}
          />
          Requiere cita previa
        </label>
        {f.appointment_required && (
          <Field label="Anticipación para pedir la cita (días)">
            <input
              type="number"
              min="0"
              max="90"
              value={f.appointment_notice_days}
              onChange={(e) =>
                change("appointment_notice_days", Number(e.target.value))
              }
            />
          </Field>
        )}
        </>}
        {!f.reception&&<p className="notice">No se inventará un horario ni se habilitará una ruta automática por guardar este cuestionario.</p>}
      </div>}
      {step===2&&<div className="form-section">
        <h3>Revisa de dónde viene la información</h3>
        <div className="form-grid">
          <Field label="Fuente de la información">
            <select
              value={f.source}
              onChange={(e) => change("source", e.target.value)}
            >
              <option value="representative">Estimación del visitador</option>
              <option value="doctor">Declarado por el médico</option>
              <option value="document">Documento consultado</option>
            </select>
          </Field>
          <Field label="Fecha de observación">
            <input
              type="date"
              required
              max={today()}
              value={f.observed_on}
              onChange={(e) => change("observed_on", e.target.value)}
            />
          </Field>
        </div>
        <Field label="Contexto de la estimación">
          <textarea
            rows={3}
            maxLength={1500}
            value={f.notes}
            onChange={(e) => change("notes", e.target.value)}
          />
        </Field>
        <div className="notice">
          <Target size={18} />
          <span>
            {f.practice_days.length * f.patients_per_day} atenciones semanales
            estimadas. Este cálculo no representa prescripción ni pacientes
            únicos.
          </span>
        </div>
      </div>}
    </Dialog>
  );
}

function PharmacyEditor({ existing, site, rep, save, close }: any) {
  const [f, set] = useState<any>({
    id: existing?.id || crypto.randomUUID(),
    representative_id: rep,
    name: site?.name || "",
    chain: existing?.chain || "Independiente",
    address: site?.address || "",
    city: site?.city || "Bogotá",
    contact: existing?.data.contact || "",
    phone: existing?.data.phone || "",
    reception: existing?.data.reception || structuredClone(emptyOpening),
    additional_reception: existing?.data.additional_reception || [],
    active: existing?.active ?? true,
  });
  const change = (k: string, v: any) => set({ ...f, [k]: v });
  return (
    <Dialog
      title={existing ? "Editar droguería" : "Nueva droguería"}
      subtitle="Registra una sede visitable, no solamente el nombre de la cadena."
      onClose={close}
      onSave={async () => {
        await save("pharmacy.save", f, existing?.version || 0);
        close();
      }}
    >
      <Field label="Nombre de la sede">
        <input
          required
          minLength={2}
          maxLength={160}
          value={f.name}
          onChange={(e) => change("name", e.target.value)}
        />
      </Field>
      <Field label="Cadena">
        <input
          required
          value={f.chain}
          onChange={(e) => change("chain", e.target.value)}
        />
      </Field>
      <Field label="Dirección completa">
        <input
          required
          minLength={5}
          value={f.address}
          onChange={(e) => change("address", e.target.value)}
        />
      </Field>
      <Field label="Ciudad">
        <input
          required
          value={f.city}
          onChange={(e) => change("city", e.target.value)}
        />
      </Field>
      <div className="form-grid">
        <Field label="Persona de contacto">
          <input
            value={f.contact}
            onChange={(e) => change("contact", e.target.value)}
          />
        </Field>
        <Field label="Teléfono">
          <input
            type="tel"
            value={f.phone}
            onChange={(e) => change("phone", e.target.value)}
          />
        </Field>
      </div>
      <Field label="Días disponibles">
        <Days
          value={f.reception.weekdays}
          onChange={(v: any) =>
            change("reception", { ...f.reception, weekdays: v })
          }
        />
      </Field>
      <div className="form-grid">
        <Field label="Desde">
          <input
            type="time"
            required
            value={f.reception.opens}
            onChange={(e) =>
              change("reception", { ...f.reception, opens: e.target.value })
            }
          />
        </Field>
        <Field label="Hasta">
          <input
            type="time"
            required
            value={f.reception.closes}
            onChange={(e) =>
              change("reception", { ...f.reception, closes: e.target.value })
            }
          />
        </Field>
      </div>
      {existing && (
        <label className="checkbox">
          <input
            type="checkbox"
            checked={f.active}
            onChange={(e) => change("active", e.target.checked)}
          />
          Sede activa
        </label>
      )}
      <small className="muted">
        Después de guardar, verifica el punto en el mapa para incluirla en rutas
        automáticas.
      </small>
    </Dialog>
  );
}

function PharmacyDetail({ item, state: s, save, open, close }: any) {
  const readOnly = s.can_edit === false;
  const site = s.sites.find((x: any) => x.id === item.institution_id),
    visits = s.pharmacy_visits.filter((x: any) => x.pharmacy_id === item.id),
    [error, setError] = useState(""),
    [reason, setReason] = useState(""),
    [notDone, setNotDone] = useState<any>(null),
    [busy, setBusy] = useState(false);
  const act = async (v: any, action: string) => {
    setBusy(true);
    setError("");
    try {
      let p: any = null;
      try {
        p = await locate();
      } catch {}
      await save(
        "pharmacy.visit." + action,
        {
          id: v.id,
          occurred_at: new Date().toISOString(),
          point: p ? { lat: p.lat, lng: p.lng } : null,
          accuracy_m: p?.accuracy_m || null,
          reason: action === "not_done" ? reason : "",
        },
        v.version,
      );
      setNotDone(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog
      title={site?.name}
      subtitle={item.chain + " · " + site?.address}
      onClose={close}
      wide
    >
      {!readOnly && <div className="inline-actions">
        <button
          type="button"
          className="button secondary small"
          onClick={() => open({ kind: "pharmacy", item })}
        >
          Editar ficha
        </button>
        <button
          type="button"
          className="button secondary small"
          onClick={() => open({ kind: "location", site })}
        >
          <MapPin size={15} />
          Verificar sede
        </button>
        <button
          type="button"
          className="button secondary small"
          onClick={() => open({ kind: "referral", item })}
        >
          Direccionamiento médico
        </button>
      </div>}
      <div className="panel-heading">
        <h3>Visitas a esta sede</h3>
        {!readOnly && <button
          type="button"
          className="text-button"
          onClick={() => open({ kind: "schedule", item })}
        >
          <Plus size={16} />
          Programar
        </button>}
      </div>
      {error && <div className="notice danger">{error}</div>}
      {!visits.length && (
        <p className="muted">
          Todavía no hay visitas. Puedes programar una o incluir esta sede en
          las reglas del rutero.
        </p>
      )}
      {visits.map((v: any) => (
        <article className="visit-item" key={v.id}>
          <div className="split">
            <h4>
              {dateLabel(v.scheduled_at)} · {localTime(v.scheduled_at)}
            </h4>
            <Tag tone={v.status === "confirmed" ? "green" : "muted"}>
              {prettyStatus[v.status]}
            </Tag>
          </div>
          {!readOnly && <div className="inline-actions">
            {v.status === "scheduled" && (
              <button
                type="button"
                disabled={busy}
                className="button small"
                onClick={() => act(v, "arrive")}
              >
                <LocateFixed size={15} />
                Llegué
              </button>
            )}
            {v.status === "in_progress" && (
              <button
                type="button"
                disabled={busy}
                className="button small"
                onClick={() => act(v, "finish")}
              >
                <Check size={15} />
                Terminé
              </button>
            )}
            {["scheduled", "in_progress"].includes(v.status) && (
              <button
                type="button"
                className="text-button"
                onClick={() => setNotDone(v)}
              >
                No se realizó
              </button>
            )}
            {["finished", "confirmed"].includes(v.status) && (
              <button
                type="button"
                className="button small secondary"
                onClick={() => open({ kind: "report", visit: v })}
              >
                <FileCheck2 size={15} />
                {v.status === "confirmed"
                  ? "Ver / corregir reporte"
                  : "Completar reporte"}
              </button>
            )}
          </div>}
          {!readOnly && notDone?.id === v.id && (
            <div className="search-action">
              <input
                aria-label="Motivo de visita no realizada"
                placeholder="Motivo…"
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
              <button
                type="button"
                className="button small"
                disabled={!reason.trim() || busy}
                onClick={() => act(v, "not_done")}
              >
                Guardar
              </button>
            </div>
          )}
          {v.location?.arrive && (
            <p className="muted">
              Ubicación de llegada:{" "}
              {v.location.arrive.geo_state || "Pendiente de sincronizar"}
              {v.location.arrive.distance_m != null
                ? ` · ${v.location.arrive.distance_m} m de la sede`
                : ""}
            </p>
          )}
          {v.report?.action && <p>{v.report.action}</p>}
        </article>
      ))}
      <div className="panel-heading">
        <h3>Direccionamientos vinculados</h3>
        <Tag>
          {s.referrals.filter((r: any) => r.pharmacy_id === item.id).length}
        </Tag>
      </div>
      <p className="muted">
        El direccionamiento documenta la recomendación de una sede. No confirma
        venta ni dispensación.
      </p>
    </Dialog>
  );
}

function ScheduleEditor({ item, save, close }: any) {
  const [date, setDate] = useState(today()),
    [at, setAt] = useState("09:00");
  return (
    <Dialog
      title="Programar visita a droguería"
      onClose={close}
      onSave={async () => {
        await save("pharmacy.visit.schedule", {
          id: crypto.randomUUID(),
          pharmacy_id: item.id,
          scheduled_at: `${date}T${at}:00-05:00`,
        });
        close();
      }}
    >
      <div className="form-grid">
        <Field label="Fecha">
          <input
            type="date"
            required
            value={date}
            onChange={(e) => setDate(e.target.value)}
          />
        </Field>
        <Field label="Hora acordada">
          <input
            type="time"
            required
            value={at}
            onChange={(e) => setAt(e.target.value)}
          />
        </Field>
      </div>
      <div className="notice">
        Esta cita queda fija. El rutero la respetará al calcular la jornada.
      </div>
    </Dialog>
  );
}

function ProductSelect({ products, value, onChange }: any) {
  return (
    <select
      required
      aria-label="Producto"
      value={value}
      onChange={(e) => onChange(e.target.value)}
    >
      <option value="">Seleccionar producto</option>
      {products.map((p: any) => (
        <option key={p.id} value={p.id}>
          {p.name}
        </option>
      ))}
    </select>
  );
}
function ReportEditor({ visit, products, save, close }: any) {
  const [f, set] = useState<any>({
    observations: visit.report?.observations || [],
    commercial: visit.report?.commercial || [],
    action: visit.report?.action || "",
    result: visit.report?.result || "unknown",
    barriers: visit.report?.barriers || "",
    followups: visit.report?.followups || [],
  });
  const change = (k: string, v: any) => set({ ...f, [k]: v });
  const update = (group: string, i: number, k: string, v: any) =>
    change(
      group,
      f[group].map((x: any, j: number) => (i === j ? { ...x, [k]: v } : x)),
    );
  return (
    <Dialog
      title="Reporte de droguería"
      subtitle="Disponibilidad, acción realizada y próximos pasos."
      onClose={close}
      wide
      saveLabel="Confirmar reporte"
      onSave={async () => {
        await save(
          "pharmacy.visit.report",
          { ...f, id: visit.id, confirmed: true },
          visit.version,
        );
        close();
      }}
    >
      <div className="form-section">
        <div className="split">
          <h3>Disponibilidad por producto</h3>
          <button
            type="button"
            className="text-button"
            onClick={() =>
              change("observations", [
                ...f.observations,
                {
                  product_id: "",
                  stock: null,
                  unit: "unidades",
                  rotation: null,
                  period_days: null,
                  source: "declared",
                },
              ])
            }
          >
            <Plus size={16} />
            Producto
          </button>
        </div>
        {!f.observations.length && (
          <p className="muted">
            Si no se verificó inventario, no lo registres como cero.
          </p>
        )}
        {f.observations.map((o: any, i: number) => (
          <div className="subform" key={i}>
            <div className="split">
              <ProductSelect
                products={products}
                value={o.product_id}
                onChange={(v: string) =>
                  update("observations", i, "product_id", v)
                }
              />
              <button
                type="button"
                className="icon-btn"
                aria-label="Quitar observación"
                onClick={() =>
                  change(
                    "observations",
                    f.observations.filter((_: any, j: number) => i !== j),
                  )
                }
              >
                <X size={16} />
              </button>
            </div>
            <div className="form-grid three">
              <Field label="Inventario">
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  placeholder="No informado"
                  value={o.stock ?? ""}
                  onChange={(e) =>
                    update(
                      "observations",
                      i,
                      "stock",
                      e.target.value === "" ? null : Number(e.target.value),
                    )
                  }
                />
              </Field>
              <Field label="Unidad">
                <input
                  required
                  value={o.unit}
                  onChange={(e) =>
                    update("observations", i, "unit", e.target.value)
                  }
                />
              </Field>
              <Field label="Fuente">
                <select
                  value={o.source}
                  onChange={(e) =>
                    update("observations", i, "source", e.target.value)
                  }
                >
                  <option value="declared">Declarado</option>
                  <option value="observed">Observado</option>
                </select>
              </Field>
              <Field label="Rotación en el periodo">
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={o.rotation ?? ""}
                  onChange={(e) =>
                    update(
                      "observations",
                      i,
                      "rotation",
                      e.target.value === "" ? null : Number(e.target.value),
                    )
                  }
                />
              </Field>
              <Field label="Periodo (días)">
                <input
                  type="number"
                  min="1"
                  max="366"
                  value={o.period_days ?? ""}
                  onChange={(e) =>
                    update(
                      "observations",
                      i,
                      "period_days",
                      e.target.value === "" ? null : Number(e.target.value),
                    )
                  }
                />
              </Field>
            </div>
          </div>
        ))}
      </div>
      <div className="form-section">
        <div className="split">
          <h3>Gestión comercial</h3>
          <button
            type="button"
            className="text-button"
            onClick={() =>
              change("commercial", [
                ...f.commercial,
                {
                  product_id: "",
                  kind: "suggested_order",
                  quantity: 1,
                  unit: "unidades",
                  value_cop: null,
                  evidence: "",
                },
              ])
            }
          >
            <Plus size={16} />
            Gestión
          </button>
        </div>
        {f.commercial.map((o: any, i: number) => (
          <div className="subform" key={i}>
            <div className="split">
              <ProductSelect
                products={products}
                value={o.product_id}
                onChange={(v: string) =>
                  update("commercial", i, "product_id", v)
                }
              />
              <button
                type="button"
                className="icon-btn"
                aria-label="Quitar gestión"
                onClick={() =>
                  change(
                    "commercial",
                    f.commercial.filter((_: any, j: number) => i !== j),
                  )
                }
              >
                <X size={16} />
              </button>
            </div>
            <Field label="Estado real">
              <select
                value={o.kind}
                onChange={(e) =>
                  update("commercial", i, "kind", e.target.value)
                }
              >
                <option value="suggested_order">Pedido sugerido</option>
                <option value="requested_order">Pedido solicitado</option>
                <option value="confirmed_transfer">
                  Transferencia confirmada
                </option>
              </select>
            </Field>
            <div className="form-grid three">
              <Field label="Cantidad">
                <input
                  required
                  type="number"
                  min="0.01"
                  step="0.01"
                  value={o.quantity}
                  onChange={(e) =>
                    update("commercial", i, "quantity", Number(e.target.value))
                  }
                />
              </Field>
              <Field label="Unidad">
                <input
                  required
                  value={o.unit}
                  onChange={(e) =>
                    update("commercial", i, "unit", e.target.value)
                  }
                />
              </Field>
              <Field label="Valor COP (opcional)">
                <input
                  type="number"
                  min="0"
                  step="0.01"
                  value={o.value_cop ?? ""}
                  onChange={(e) =>
                    update(
                      "commercial",
                      i,
                      "value_cop",
                      e.target.value === "" ? null : Number(e.target.value),
                    )
                  }
                />
              </Field>
            </div>
            <Field label="Soporte o referencia">
              <input
                required={o.kind === "confirmed_transfer"}
                value={o.evidence}
                onChange={(e) =>
                  update("commercial", i, "evidence", e.target.value)
                }
              />
            </Field>
          </div>
        ))}
      </div>
      <Field label="¿Qué gestión realizaste?">
        <textarea
          rows={3}
          required
          minLength={3}
          maxLength={1500}
          value={f.action}
          onChange={(e) => change("action", e.target.value)}
        />
      </Field>
      <Field label="Resultado del objetivo">
        <select
          value={f.result}
          onChange={(e) => change("result", e.target.value)}
        >
          <option value="unknown">No informado</option>
          <option value="achieved">Logrado</option>
          <option value="partial">Parcial</option>
          <option value="not_achieved">No logrado</option>
        </select>
      </Field>
      <Field label="Barreras y dificultades">
        <textarea
          rows={2}
          maxLength={1500}
          value={f.barriers}
          onChange={(e) => change("barriers", e.target.value)}
        />
      </Field>
      <div className="form-section">
        <div className="split">
          <h3>Próximos pasos</h3>
          <button
            type="button"
            className="text-button"
            onClick={() =>
              change("followups", [
                ...f.followups,
                { action: "", due_on: future(1), owner: "representative" },
              ])
            }
          >
            <Plus size={16} />
            Pendiente
          </button>
        </div>
        {f.followups.map((x: any, i: number) => (
          <div className="subform" key={i}>
            <Field label="Acción acordada">
              <input
                required
                minLength={3}
                value={x.action}
                onChange={(e) =>
                  update("followups", i, "action", e.target.value)
                }
              />
            </Field>
            <div className="form-grid">
              <Field label="Fecha">
                <input
                  type="date"
                  required
                  value={x.due_on}
                  onChange={(e) =>
                    update("followups", i, "due_on", e.target.value)
                  }
                />
              </Field>
              <Field label="Responsable">
                <select
                  value={x.owner}
                  onChange={(e) =>
                    update("followups", i, "owner", e.target.value)
                  }
                >
                  <option value="representative">Visitador</option>
                  <option value="commercial">Equipo comercial</option>
                </select>
              </Field>
            </div>
            <button
              type="button"
              className="text-button danger-text"
              onClick={() =>
                change(
                  "followups",
                  f.followups.filter((_: any, j: number) => j !== i),
                )
              }
            >
              Quitar pendiente
            </button>
          </div>
        ))}
      </div>
    </Dialog>
  );
}

function ReferralEditor({ pharmacy, state: s, save, close }: any) {
  const [visit, setVisit] = useState(""),
    [product, setProduct] = useState(""),
    [note, setNote] = useState("");
  return (
    <Dialog
      title="Direccionamiento médico"
      subtitle="Relaciona la visita en la que se recomendó esta sede."
      onClose={close}
      onSave={async () => {
        await save("referral.create", {
          id: crypto.randomUUID(),
          visit_id: visit,
          pharmacy_id: pharmacy.id,
          product_ids: [product],
          note,
        });
        close();
      }}
    >
      <Field label="Visita de origen">
        <select
          required
          value={visit}
          onChange={(e) => setVisit(e.target.value)}
        >
          <option value="">Selecciona una visita</option>
          {s.visits
            .filter((v: any) => ["finished", "confirmed"].includes(v.status))
            .map((v: any) => (
              <option key={v.id} value={v.id}>
                {s.doctors.find((d: any) => d.id === v.doctor_id)?.name} ·{" "}
                {dateLabel(v.scheduled_at)}
              </option>
            ))}
        </select>
      </Field>
      <Field label="Producto">
        <ProductSelect
          products={s.products}
          value={product}
          onChange={setProduct}
        />
      </Field>
      <Field label="Contexto del direccionamiento">
        <textarea
          value={note}
          maxLength={1000}
          onChange={(e) => setNote(e.target.value)}
        />
      </Field>
      <div className="notice">
        Este registro no confirma inventario, dispensación ni venta.
      </div>
    </Dialog>
  );
}

function PolicyEditor({ existing, rep, save, close }: any) {
  const [f, set] = useState<any>(
    existing
      ? { ...structuredClone(existing.data), active: existing.active }
      : {
          active: false,
          publish_automatically: true,
          origin: { lat: 4.67, lng: -74.08 },
          origin_label: "",
          return_to_origin: false,
          weekdays: [0, 1, 2, 3, 4],
          starts: "08:00",
          ends: "17:00",
          lunch_starts: "12:00",
          lunch_ends: "13:00",
          travel_mode: "car",
          medical_minutes: 20,
          pharmacy_minutes: 20,
          max_contacts: 12,
        },
  );
  const [err, setErr] = useState(""),
    [originConfirmed, setOriginConfirmed] = useState(!!existing);
  const change = (k: string, v: any) => set({ ...f, [k]: v });
  return (
    <Dialog
      title="Política de planeación"
      subtitle="Esta configuración autoriza la generación automática del recorrido."
      onClose={close}
      wide
      onSave={async () => {
        if (!originConfirmed)
          throw new Error("Confirma el punto real de salida del visitador");
        await save(
          "policy.save",
          { ...Object.fromEntries(Object.entries(f).filter(([k])=>k!=="panel_import_hash")), representative_id: rep },
          existing?.version || 0,
        );
        close();
      }}
    >
      <div className="form-section">
        <h3>Jornada y pausas</h3>
        <Field
          label="Fechas sin trabajo"
          hint="Festivos, permisos o ausencias. Una fecha YYYY-MM-DD por línea."
        >
          <textarea
            rows={3}
            value={(f.excluded_dates || []).join("\n")}
            onChange={(e) =>
              change(
                "excluded_dates",
                e.target.value.split("\n").filter(Boolean),
              )
            }
          />
        </Field>
        <Field label="Días laborales">
          <Days
            value={f.weekdays}
            onChange={(v: any) => change("weekdays", v)}
          />
        </Field>
        <div className="form-grid">
          {[
            ["starts", "Inicio de jornada"],
            ["ends", "Fin de jornada"],
            ["lunch_starts", "Inicio de almuerzo"],
            ["lunch_ends", "Fin de almuerzo"],
          ].map(([k, label]) => (
            <Field key={k} label={label}>
              <input
                type="time"
                required
                value={f[k]}
                onChange={(e) => change(k, e.target.value)}
              />
            </Field>
          ))}
        </div>
      </div>
      <div className="form-section">
        <h3>Punto real de salida</h3>
        <p className="muted">
          Selecciona el origen acordado con el visitador. El mapa inicial solo
          sirve para ubicarte.
        </p>
        <Field label="Nombre o referencia del punto">
          <input
            required
            minLength={2}
            value={f.origin_label}
            onChange={(e) => change("origin_label", e.target.value)}
            placeholder="Oficina, sede o punto acordado…"
          />
        </Field>
        <TerritoryMap
          selected={f.origin}
          onSelect={(p) => {
            change("origin", p);
            setOriginConfirmed(false);
          }}
        />
        <div className="coordinates">
          <span>
            {f.origin.lat.toFixed(5)}, {f.origin.lng.toFixed(5)}
          </span>
          <button
            type="button"
            className="text-button"
            onClick={async () => {
              try {
                const p = await locate();
                change("origin", { lat: p.lat, lng: p.lng });
              } catch (e) {
                setErr((e as Error).message);
              }
            }}
          >
            <LocateFixed size={16} />
            Usar mi ubicación
          </button>
        </div>
        {err && <p className="danger-text">{err}</p>}
        <label className="checkbox">
          <input
            type="checkbox"
            checked={originConfirmed}
            onChange={(e) => setOriginConfirmed(e.target.checked)}
          />
          Confirmo que este es el punto real de salida del visitador
        </label>
        <label className="checkbox">
          <input
            type="checkbox"
            checked={f.return_to_origin}
            onChange={(e) => change("return_to_origin", e.target.checked)}
          />
          Incluir regreso al punto de salida
        </label>
      </div>
      <div className="form-grid">
        <Field
          label="Minutos por parada médica"
          hint="Incluye acceso, visita y reporte."
        >
          <input
            type="number"
            required
            min="5"
            max="180"
            value={f.medical_minutes}
            onChange={(e) => change("medical_minutes", Number(e.target.value))}
          />
        </Field>
        <Field label="Minutos por droguería">
          <input
            type="number"
            required
            min="5"
            max="180"
            value={f.pharmacy_minutes}
            onChange={(e) => change("pharmacy_minutes", Number(e.target.value))}
          />
        </Field>
      </div>
      <div className="notice">
        Desplazamiento en carro. Máximo habitual: 12 contactos totales. Cada
        excepción requiere revisión de una versión concreta.
      </div>
      <label className="checkbox">
        <input
          type="checkbox"
          checked={f.active}
          onChange={(e) => change("active", e.target.checked)}
        />
        Activar generación automática para este visitador
      </label>
      <label className="checkbox">
        <input
          type="checkbox"
          checked={f.publish_automatically}
          onChange={(e) => change("publish_automatically", e.target.checked)}
        />
        Publicar automáticamente planes válidos de hasta 12 contactos
      </label>
      <label className="checkbox"><input type="checkbox" checked={!!f.allow_unconfirmed_reception} onChange={e=>change("allow_unconfirmed_reception",e.target.checked)}/>Permitir propuestas con horario pendiente de confirmar</label>
      <p className="muted">Estas paradas se señalan como provisionales. Se usa la jornada del visitador; no equivale a una cita confirmada.</p>
    </Dialog>
  );
}

function RequirementEditor({ existing, state: s, save, close }: any) {
  const [kind, setKind] = useState(
      existing?.pharmacy_id ? "pharmacy" : "doctor",
    ),
    [target, setTarget] = useState(
      existing?.doctor_id || existing?.pharmacy_id || "",
    ),
    [f, set] = useState<any>(
      existing
        ? {
            windows: structuredClone(existing.data.windows),
            min_gap_days: existing.data.min_gap_days,
            product_sequence: structuredClone(existing.data.product_sequence),
            service_minutes: existing.data.service_minutes,
            priority: existing.data.priority,
            cycle_start: existing.cycle_start,
            cycle_end: existing.cycle_end,
            active: existing.active,
          }
        : {
            cycle_start: today(),
            cycle_end: future(27),
            windows: [{ start: today(), end: future(27) }],
            min_gap_days: 6,
            product_sequence: [],
            service_minutes: 20,
            priority: 1,
            active: true,
          },
    );
  const change = (k: string, v: any) => set({ ...f, [k]: v });
  return (
    <Dialog
      title="Frecuencia y secuencia del contacto"
      onClose={close}
      wide
      onSave={async () => {
        await save(
          "requirement.save",
          {
            ...f,
            id: existing?.id || crypto.randomUUID(),
            representative_id: s.representative_id,
            doctor_id: kind === "doctor" ? target : null,
            institution_id: kind === "doctor" ? (existing?.institution_id || s.doctors.find((d:any)=>d.id===target)?.institution_id) : null,
            pharmacy_id: kind === "pharmacy" ? target : null,
          },
          existing?.version || 0,
        );
        close();
      }}
    >
      <div className="form-grid">
        <Field label="Tipo de destino">
          <select
            disabled={!!existing}
            value={kind}
            onChange={(e) => {
              setKind(e.target.value);
              setTarget("");
            }}
          >
            <option value="doctor">Médico</option>
            <option value="pharmacy">Droguería</option>
          </select>
        </Field>
        <Field label="Contacto">
          <select
            required
            disabled={!!existing}
            value={target}
            onChange={(e) => setTarget(e.target.value)}
          >
            <option value="">Seleccionar</option>
            {(kind === "doctor" ? s.doctors : s.pharmacies).map((x: any) => (
              <option key={x.id} value={x.id}>
                {x.name ||
                  s.sites.find((i: any) => i.id === x.institution_id)?.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Inicio del ciclo">
          <input
            type="date"
            required
            value={f.cycle_start}
            onChange={(e) => change("cycle_start", e.target.value)}
          />
        </Field>
        <Field label="Fin del ciclo">
          <input
            type="date"
            required
            value={f.cycle_end}
            onChange={(e) => change("cycle_end", e.target.value)}
          />
        </Field>
      </div>
      <div className="form-section">
        <div className="split">
          <h3>{f.windows.length} impactos exigibles</h3>
          <button
            type="button"
            className="text-button"
            onClick={() =>
              change("windows", [
                ...f.windows,
                { start: f.cycle_start, end: f.cycle_end },
              ])
            }
          >
            <Plus size={16} />
            Impacto
          </button>
        </div>
        <p className="muted">
          Define una ventana por impacto. Deben estar ordenadas y no
          superponerse.
        </p>
        {f.windows.map((w: any, i: number) => (
          <div className="window-row" key={i}>
            <b>{i + 1}</b>
            <Field label="Desde">
              <input
                type="date"
                required
                value={w.start}
                onChange={(e) =>
                  change(
                    "windows",
                    f.windows.map((x: any, j: number) =>
                      i === j ? { ...x, start: e.target.value } : x,
                    ),
                  )
                }
              />
            </Field>
            <Field label="Hasta">
              <input
                type="date"
                required
                value={w.end}
                onChange={(e) =>
                  change(
                    "windows",
                    f.windows.map((x: any, j: number) =>
                      i === j ? { ...x, end: e.target.value } : x,
                    ),
                  )
                }
              />
            </Field>
            <button
              type="button"
              className="icon-btn"
              disabled={f.windows.length === 1}
              aria-label="Quitar impacto"
              onClick={() =>
                change(
                  "windows",
                  f.windows.filter((_: any, j: number) => i !== j),
                )
              }
            >
              <X size={16} />
            </button>
          </div>
        ))}
      </div>
      <div className="form-grid three">
        <Field label="Separación (días calendario)">
          <input
            required
            type="number"
            min="1"
            max="90"
            value={f.min_gap_days}
            onChange={(e) => change("min_gap_days", Number(e.target.value))}
          />
        </Field>
        <Field label="Duración total de parada (min)">
          <input
            required
            type="number"
            min="5"
            max="180"
            value={f.service_minutes}
            onChange={(e) => change("service_minutes", Number(e.target.value))}
          />
        </Field>
        <Field label="Prioridad gerencial (1–5)">
          <input
            required
            type="number"
            min="1"
            max="5"
            value={f.priority}
            onChange={(e) => change("priority", Number(e.target.value))}
          />
        </Field>
      </div>
      <Field
        label="Secuencia de productos planeada"
        hint="Selecciona en orden. Máximo cinco productos."
      >
        <select
          value=""
          onChange={(e) => {
            if (
              e.target.value &&
              f.product_sequence.length < 5 &&
              !f.product_sequence.includes(e.target.value)
            )
              change("product_sequence", [
                ...f.product_sequence,
                e.target.value,
              ]);
          }}
        >
          <option value="">Agregar producto a la secuencia…</option>
          {s.products.map((p: any) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </Field>
      <div className="sequence">
        {f.product_sequence.map((id: string, i: number) => (
          <button
            type="button"
            key={id}
            onClick={() =>
              change(
                "product_sequence",
                f.product_sequence.filter((x: string) => x !== id),
              )
            }
          >
            {i + 1}. {s.products.find((p: any) => p.id === id)?.name}
            <X size={13} />
          </button>
        ))}
      </div>
      <label className="checkbox">
        <input
          type="checkbox"
          checked={f.active}
          onChange={(e) => change("active", e.target.checked)}
        />
        Regla activa
      </label>
    </Dialog>
  );
}

function GenerateEditor({ day, rep, save, close }: any) {
  const [max, setMax] = useState(12);
  return (
    <Dialog
      title="Calcular propuesta de ruta"
      subtitle={day}
      onClose={close}
      saveLabel="Calcular propuesta"
      onSave={async () => {
        if (!navigator.onLine)
          throw new Error("Conéctate para solicitar una nueva ruta");
        await save("route.generate", {
          representative_id: rep,
          day,
          max_contacts: max,
        });
        close();
      }}
    >
      <Field label="Máximo de contactos">
        <input
          type="number"
          required
          min="1"
          max="20"
          value={max}
          onChange={(e) => setMax(Number(e.target.value))}
        />
      </Field>
      <div className="notice">
        {max > 12
          ? "Esta propuesta supera 12 contactos. No se publicará automáticamente; requerirá tu aprobación y un motivo."
          : "El sistema respetará citas, ventanas de frecuencia, almuerzo y tiempo de conducción."}
      </div>
      <p className="muted">
        Los contactos que no se asignen quedan visibles con su motivo. Una
        propuesta no cambia la agenda hasta su publicación.
      </p>
    </Dialog>
  );
}
function PublishEditor({ plan, save, close }: any) {
  const [reason, setReason] = useState("");
  return (
    <Dialog
      title="Publicar esta versión"
      subtitle={`Versión ${plan.version} · ${plan.stops.length} contactos · ${plan.day}`}
      onClose={close}
      saveLabel="Publicar ruta"
      onSave={async () => {
        if (!navigator.onLine)
          throw new Error("Conéctate para publicar la ruta");
        await save("route.publish", { id: plan.id, reason }, plan.version);
        close();
      }}
    >
      <p>
        Se actualizará la agenda del visitador y se conservarán las visitas ya
        iniciadas.
      </p>
      {plan.max_contacts > 12 && (
        <div className="notice">
          Excepción de capacidad: autorizas hasta {plan.max_contacts} contactos
          para esta versión. Las demás restricciones siguen vigentes.
        </div>
      )}
      <Field
        label={
          plan.max_contacts > 12
            ? "Motivo de la excepción (obligatorio)"
            : "Nota de publicación"
        }
      >
        <textarea
          required={plan.max_contacts > 12}
          minLength={plan.max_contacts > 12 ? 10 : 0}
          maxLength={1000}
          rows={4}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
        />
      </Field>
    </Dialog>
  );
}

function CatalogPanel({data, day}:{data:any;day:string}) {
  const [search,setSearch]=useState("");
  const [page,setPage]=useState(0);
  const normalize=(s:string)=>s.normalize("NFD").replace(/[\u0300-\u036f]/g,"").toLowerCase();
  const all=data.presentations || [];
  const found=all.filter((x:any)=>normalize(x.name+" "+(x.barcode || "")).includes(normalize(search)));
  const cycle=(data.cycles || []).find((x:any)=>x.starts_on<=day&&x.ends_on>=day);
  return <>
    <section className="origin-banner"><CalendarDays size={28}/><div><span className="eyebrow">CICLO COMERCIAL</span><h3>{cycle?`${cycle.code} · ${dateLabel(cycle.starts_on+"T12:00:00-05:00")} al ${dateLabel(cycle.ends_on+"T12:00:00-05:00")}`:"Sin ciclo publicado para esta fecha"}</h3><p>{cycle?`${cycle.working_days} días hábiles · La frecuencia FZ corresponde a cada sede dentro de este ciclo.`:"Consulta con gerencia el calendario vigente."}</p></div></section>
    <div className="toolbar"><label className="catalog-search"><Search size={18}/><input type="search" aria-label="Buscar presentación o código de barras" placeholder="Buscar presentación o código de barras" value={search} onChange={e=>{setSearch(e.target.value);setPage(0)}}/></label></div>
    <section className="panel"><div className="panel-heading"><h3>{all.length} presentaciones SNC</h3><span className="muted">Catálogo comercial</span></div>
      {found.slice(page*10,page*10+10).map((x:any)=><article className="list-item catalog-item" key={x.id}><div className="item-main"><b>{x.name}</b><small>{x.barcode ? `Código de barras: ${x.barcode}` : "Código de barras pendiente de suministro"}</small><div className="contact-tags"><Tag tone="muted">{data.products.find((p:any)=>p.id===x.product_id)?.name || "SNC"}</Tag><Tag tone="muted">{x.pack_units != null ? `${x.pack_units} unidad(es) por empaque` : "Empaque pendiente de confirmar"}</Tag></div><details><summary>Ver procedencia</summary><small>{x.source.file}{x.source.sheet ? ` · Hoja ${x.source.sheet}` : ""}{x.source.row ? ` · Fila ${x.source.row}` : ""}{x.source.slide ? ` · Diapositiva ${x.source.slide}` : ""}</small><small>La presentación no acredita existencias en droguería.</small></details></div></article>)}
      {!found.length&&<p className="empty">No hay presentaciones que coincidan con la búsqueda.</p>}
      <ListPager total={found.length} page={page} setPage={setPage}/>
    </section>
  </>;
}

function ConnectedApp(){const [identity,setIdentity]=useState<User|null>(null);return <><App onIdentity={setIdentity}/>{identity&&<AppNavigation user={identity}/>}</>}
createRoot(document.getElementById("root")!).render(<ConnectedApp />);
