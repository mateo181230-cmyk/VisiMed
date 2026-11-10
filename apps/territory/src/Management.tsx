import { Performance } from "./Performance";
import { Commercial } from "./Commercial";
import {Signals} from './Signals';
import {ReferencePanel,SourceFiles} from './Reference';
import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowUpRight,
  BarChart3,
  CalendarDays,
  CheckCheck,
  Download,
  Megaphone,
  RefreshCw,
  Search,
  Send,
  ShieldCheck,
  Sparkles,
  Target,
  Users,
} from "lucide-react";
import { api, downloadReport, type User } from "./api";
import {
  activityStatuses,
  downloadMarketing,
  humanDate,
  localDateTime,
} from "./Marketing";
import "./management.css";

const number = (n: any) =>
  n == null ? "—" : Number(n).toLocaleString("es-CO");
function Bars({
  items,
  color = "green",
  suffix = "",
}: {
  items: any[];
  color?: string;
  suffix?: string;
}) {
  const max = Math.max(1, ...items.map((x) => x.value));
  return !items.length ? (
    <div className="mg-chart-empty">
      Aún no hay resultados registrados en este período.
    </div>
  ) : (
    <div className={"mg-bars " + color}>
      {items.slice(0, 8).map((x) => (
        <div key={x.name}>
          <div>
            <span>{x.name}</span>
            <b>
              {number(x.value)} {suffix}
            </b>
          </div>
          <span className="mg-bar-track">
            <i style={{ width: Math.max(1, (x.value / max) * 100) + "%" }} />
          </span>
        </div>
      ))}
    </div>
  );
}
function Trend({ rows }: { rows: any[] }) {
  const max = Math.max(1, ...rows.map((x) => Math.max(x.planned, x.finished)));
  const width = 900,
    height = 190,
    gap = width / Math.max(1, rows.length),
    bar = Math.max(2, Math.min(18, gap / 3));
  return (
    <>
      <div className="mg-legend">
        <span>
          <i /> Programadas
        </span>
        <span>
          <i /> Terminadas
        </span>
      </div>
      <div
        className="mg-trend"
        role="img"
        aria-label="Visitas programadas y terminadas por día"
      >
        <svg viewBox="0 0 960 240">
          {[0, 0.5, 1].map((t) => (
            <g key={t}>
              <line
                x1={32}
                x2={945}
                y1={200 - t * height}
                y2={200 - t * height}
                stroke="#e7ece9"
              />
              <text
                x={25}
                y={204 - t * height}
                textAnchor="end"
                fill="#65776e"
                fontSize={11}
              >
                {Math.round(max * t)}
              </text>
            </g>
          ))}
          {rows.map((r, i) => {
            const x = 35 + gap * i;
            return (
              <g key={r.day}>
                <title>
                  {r.day}: {r.planned} programadas, {r.finished} terminadas,{" "}
                  {r.reports} reportes confirmados
                </title>
                <rect
                  x={x}
                  y={200 - (r.planned / max) * height}
                  width={bar}
                  height={(r.planned / max) * height}
                  rx={2}
                  fill="#d5e6dd"
                />
                <rect
                  x={x + bar + 2}
                  y={200 - (r.finished / max) * height}
                  width={bar}
                  height={(r.finished / max) * height}
                  rx={2}
                  fill="#216b4e"
                />
                {(i % Math.max(1, Math.ceil(rows.length / 12)) === 0 ||
                  i === rows.length - 1) && (
                  <text
                    x={x + bar}
                    y={224}
                    textAnchor="middle"
                    fill="#65776e"
                    fontSize={11}
                  >
                    {r.day.slice(8)}/{r.day.slice(5, 7)}
                  </text>
                )}
              </g>
            );
          })}
        </svg>
      </div>
    </>
  );
}
export function ManagementScreen({ user }: { user: User }) {
  const [demo,setDemo]=useState(new URLSearchParams(location.search).get('demo')==='true');
  const [pdfBusy,setPdfBusy]=useState(false);
  const today = localDateTime(new Date().toISOString()).slice(0, 10);
  const [start, setStart] = useState(
      localDateTime(new Date(Date.now() - 6 * 86400000).toISOString()).slice(
        0,
        10,
      ),
    ),
    [end, setEnd] = useState(today),
    [rep, setRep] = useState(""),
    [data, setData] = useState<any>(null),
    [allReps, setAllReps] = useState<any[]>([]),
    [error, setError] = useState(""),
    [loading, setLoading] = useState(true),
    [tab, setTab] = useState(() => {
      const view = new URLSearchParams(location.search).get("view") || "overview";
      return ["overview", "performance", "commercial", "team", "visits", "marketing", "signals", "data"].includes(view) ? view : "overview";
    }),
    [query, setQuery] = useState(""),
    [page, setPage] = useState(0),
    [question, setQuestion] = useState(""),
    [answer, setAnswer] = useState<any>(null),
    [asking, setAsking] = useState(false),
    [aiError, setAiError] = useState("");
  const request = useRef(0);
  useEffect(() => {
    if (data && tab === "commercial" && data.profile !== "line") setTab("overview");
  }, [data, tab]);
  async function load() {
    const id = ++request.current;
    try {
      const d = await api(
        `/dashboard?start=${start}&end=${end}&demo=${demo}${rep ? "&representative_id=" + rep : ""}`,
      );
      if (id !== request.current) return;
      setData(d);
      if (!rep) setAllReps(d.team);
      setError("");
    } catch (e) {
      if (id === request.current) setError((e as Error).message);
    } finally {
      if (id === request.current) setLoading(false);
    }
  }
  useEffect(() => {
    setLoading(true);
    setData(null);
    setAnswer(null);
    load();
    const t = setInterval(() => {
      if (document.visibilityState === "visible") load();
    }, 20000);
    return () => {
      clearInterval(t);
      request.current++;
    };
  }, [start, end, rep, demo]);
  useEffect(() => {
    setPage(0);
    setQuery("");
  }, [tab, rep, start, end]);
  const ask = async (text = question) => {
    if (text.trim().length < 5) return;
    setAsking(true);
    setAiError("");
    setAnswer(null);
    try {
      setAnswer(
        await api("/dashboard/ask", {
          question: text,
          start,
          end,
          representative_id: rep || null,
          demo,
        }),
      );
    } catch (e) {
      setAiError((e as Error).message);
    } finally {
      setAsking(false);
    }
  };
  const c = data?.counts;
  async function exportPdf(){setPdfBusy(true);try{const blob=await downloadReport(`/dashboard/report.pdf?start=${start}&end=${end}&demo=${demo}${rep?'&representative_id='+rep:''}`);const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=`VisiMed-SNC-${start}-${end}.pdf`;a.click();setTimeout(()=>URL.revokeObjectURL(url),30000)}catch(e:any){setError(e.message)}finally{setPdfBusy(false)}}
  const records =
    (tab === "marketing"
      ? data?.activities
      : tab === "team"
        ? data?.team
        : data?.visits) || [];
  const filtered = records.filter((r: any) =>
    JSON.stringify(r).toLocaleLowerCase().includes(query.toLocaleLowerCase()),
  );
  return (
    <div className="mg-shell dashboard-shell">
      <header className="mg-header">
        <a className="mg-back" href="/territorio/">
          <ArrowLeft size={19} /> Operación
        </a>
        <span className="mg-wordmark">
          VisiMed<span> / Gerencia</span>
        </span>
        <span className="mg-header-user">
          <ShieldCheck size={16} />
          {user.name}
        </span>
      </header>
      <div className="mg-dashboard-layout">
        <aside className="mg-dashboard-nav">
          <div className="mg-eyebrow">GESTIÓN DEL PILOTO</div>
          {[
            { id: "overview", icon: BarChart3, label: "Panorama" },
            {id:'data',icon:Users,label:'Datos y fuentes'},
            { id: "performance", icon: Target, label: data?.profile === "district" ? "Ejecución y frecuencia" : "Marcas y resultados" },
            {id:"signals",icon:Sparkles,label:"Señales y proyección"},
            ...(data?.profile === "line" ? [{ id: "commercial", icon: BarChart3, label: "Cortes comerciales" }] : []),
            { id: "team", icon: Users, label: "Equipo" },
            { id: "visits", icon: CheckCheck, label: "Visitas y reportes" },
            { id: "marketing", icon: Megaphone, label: "Mercadeo" },
          ].map((n) => (
            <button
              key={n.id}
              onClick={() => setTab(n.id)}
              className={tab === n.id ? "selected" : ""}
            >
              <n.icon size={18} />
              {n.label}
            </button>
          ))}
          <div className="mg-nav-foot">
            <span>SNC · BOGOTÁ</span>
            <p>
              La misma operación.
              <br />
              Una lectura compartida.
            </p>
            <a href="/territorio/?module=marketing">
              Gestionar actividades <ArrowUpRight size={14} />
            </a>
          </div>
        </aside>
        <main className="mg-dashboard-main">
          <div className="mg-eyebrow">
            PILOTO SNC ·{" "}
            {data?.profile === "training"
              ? "ENTRENAMIENTO"
              : data?.profile === "district"
                ? "DISTRITO"
                : "LÍNEA"}
          </div>
          <div className="mg-title-row">
            <div>
              <h1>
                {tab === 'data' ? 'Toda la base, conectada.' : tab === "overview"
                  ? "Del campo a la decisión."
                  : tab === "performance" ? (data?.profile === "district" ? "Del plan a la visita." : "Cada marca, con evidencia.") : tab === "commercial" ? "Mercado, con contexto." : tab === "team"
                    ? "Tu equipo, en contexto."
                    : tab === "marketing"
                      ? "Mercadeo con resultados."
                      : "Cada visita, verificable."}
              </h1>
              <p>
                Lee lo que está ocurriendo y abre el registro que lo explica.
              </p>
            </div>
            <button
              className="mg-secondary"
              onClick={load}
              aria-label="Actualizar dashboard"
            >
              <RefreshCw size={16} /> Actualizar
            </button>
          </div>
          <div className="mg-dashboard-filters">
            <label>Vista<select aria-label="Vista de datos" value={demo?'demo':'pilot'} onChange={e=>{setDemo(e.target.value==='demo');setRep('');setAllReps([]);setTab('overview')}}><option value="pilot">Piloto real</option><option value="demo">Demo en Novamed</option></select></label>
            <label>
              Desde
              <input
                type="date"
                max={end}
                value={start}
                onChange={(e) => setStart(e.target.value)}
              />
            </label>
            <label>
              Hasta
              <input
                type="date"
                min={start}
                value={end}
                onChange={(e) => setEnd(e.target.value)}
              />
            </label>
            <label>
              Visitador
              <select value={rep} onChange={(e) => setRep(e.target.value)}>
                <option value="">{demo?'Juliana · Demostración':'Los tres visitadores'}</option>
                {allReps.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name}
                  </option>
                ))}
              </select>
            </label>
            <div className="mg-refresh-note">
              <span className={error ? "stale" : ""} />
              {data
                ? `Actualizado ${new Date(data.as_of).toLocaleTimeString("es-CO", { timeZone: "America/Bogota" })}`
                : "Consultando datos"}
              <small>Actualización cada 20 s · Bogotá</small>
            </div>
          </div>
          {error && (
            <div className="mg-error" role="alert">
              {error}
              {data &&
                " · Los datos visibles corresponden a la última actualización exitosa."}
            </div>
          )}
          {loading && !data && (
            <div className="mg-empty">Cargando indicadores del equipo…</div>
          )}
          {data && (
            <>
              <div className="connected-links"><button className="mg-pdf-button" disabled={pdfBusy||!!error} onClick={exportPdf}><Download size={17}/>{pdfBusy?'Generando PDF…':'Descargar informe PDF'}</button><a href="/territorio/?module=calendar">Abrir calendario del equipo</a></div>
                {demo&&<p className="mg-demo-banner">DEMOSTRACIÓN CON DATOS REALES · Paneles, ubicaciones, materiales y cortes importados de Novamed. Las visitas de prueba se muestran aparte y no suman al piloto.</p>}
                {demo&&tab==='overview'&&data.reference&&<ReferencePanel data={data.reference}/>}
                {demo&&<h2 className="ref-operation-title">Resultado de la visita de demostración</h2>}
              <section className="mg-kpis">
                <article>
                  <div>
                    <CheckCheck size={18} /> Visitas terminadas
                  </div>
                  <strong>{number(c.finished_visits)}</strong>
                  <p>
                    {number(c.scheduled_visits)} programadas ·{" "}
                    {c.cancelled_visits} no realizadas
                  </p>
                </article>
                <article>
                  <div>
                    <Target size={18} /> Cobertura del panel
                  </div>
                  <strong>
                    {number(c.coverage_rate)}
                    <small>%</small>
                  </strong>
                  <p>
                    {c.covered_doctors} de {c.panel_doctors} médicos únicos
                  </p>
                </article>
                <article>
                  <div>
                    <ShieldCheck size={18} /> Reportes confirmados
                  </div>
                  <strong>
                    {number(c.report_rate)}
                    <small>%</small>
                  </strong>
                  <p>
                    {c.confirmed_reports} confirmados · {c.pending_reports}{" "}
                    pendientes
                  </p>
                </article>
                <article className="mg-kpi-accent">
                  <div>
                    <Megaphone size={18} /> Actividades realizadas
                  </div>
                  <strong>{number(c.marketing_completed)}</strong>
                  <p>
                    {c.attendances} asistencias · {c.marketing_planned}{" "}
                    programadas
                  </p>
                </article>
              </section>
              {tab === 'data' ? <>{data.reference&&<ReferencePanel data={data.reference}/>}<SourceFiles/></> : tab === "signals" ? <Signals data={data}/> : tab === "commercial" ? <Commercial user={user}/> : tab === "performance" ? <Performance data={data}/> : tab === "overview" ? (
                <>
                  <div className="mg-panel-grid">
                    <section className="mg-panel mg-span-two">
                      <div className="mg-panel-title">
                        <div>
                          <h2>Ritmo del equipo</h2>
                          <p>Visitas por fecha programada</p>
                        </div>
                        <CalendarDays size={18} />
                      </div>
                      <Trend rows={data.trend} />
                      {!c.scheduled_visits && (
                        <p className="mg-footnote">
                          Sin visitas registradas para este período. Cambia las
                          fechas para explorar la operación.
                        </p>
                      )}
                    </section>
                    <section className="mg-panel">
                      <h2>Requiere atención</h2>
                      <p>Señales verificables de la operación</p>
                      <div className="mg-alerts">
                        {data.alerts.length ? (
                          data.alerts.map((a: any, i: number) => (
                            <a
                              key={i}
                              href={
                                a.target === "marketing"
                                  ? `/territorio/?module=marketing&activity=${a.id}`
                                  : a.target === "tasks"
                                    ? "/territorio/?module=tasks"
                                    : a.target === "route"
                                      ? "/territorio/"
                                      : "#"
                              }
                              onClick={(e) => {
                                if (a.target === "visits") {
                                  e.preventDefault();
                                  setTab("visits");
                                }
                              }}
                            >
                              <span className={"mg-alert-dot " + a.level} />
                              <div>
                                <strong>{a.title}</strong>
                                <small>{a.detail}</small>
                              </div>
                              <ArrowUpRight size={14} />
                            </a>
                          ))
                        ) : (
                          <div className="mg-chart-empty">
                            Sin alertas con los datos disponibles.
                          </div>
                        )}
                      </div>
                    </section>
                  </div>
                  <div className="mg-panel-grid">
                    <section className="mg-panel">
                      <h2>Alcance por marca</h2>
                      <p>Asistencias a actividades realizadas</p>
                      <Bars items={data.products} />
                      <small className="mg-footnote">
                        Un asistente puede estar expuesto a varias marcas. No
                        representa venta ni prescripción.
                      </small>
                    </section>
                    <section className="mg-panel">
                      <h2>Especialidades alcanzadas</h2>
                      <p>Médicos relacionados en cada actividad</p>
                      <Bars items={data.specialties} color="amber" />
                    </section>
                    <section className="mg-panel">
                      <h2>Listos para salir</h2>
                      <p>
                        Calidad del panel activo · {c.panel_sites} contactos por
                        sede
                      </p>
                      <Bars
                        items={[
                          {
                            name: "Ubicación verificada",
                            value: c.verified_locations,
                          },
                          {
                            name: "Horario confirmado",
                            value: c.confirmed_hours,
                          },
                        ]}
                      />
                      <div className="mg-mini-metrics">
                        <span>
                          <b>{c.pharmacy_finished}</b> visitas a droguerías
                          terminadas
                        </span>
                        <span>
                          <b>{c.overdue_tasks}</b> compromisos vencidos hoy
                        </span>
                      </div>
                      <a className="mg-inline-link" href="/territorio/">
                        Abrir territorio <ArrowUpRight size={15} />
                      </a>
                    </section>
                  </div>
                </>
              ) : (
                <section className="mg-panel">
                  <div className="mg-panel-title">
                    <div>
                      <h2>
                        {tab === "team"
                          ? "Resultados por visitador"
                          : tab === "marketing"
                            ? "Actividades del período"
                            : "Registros que explican los indicadores"}
                      </h2>
                      <p>
                        {tab === "team"
                          ? "Las diferencias de panel y disponibilidad importan al comparar."
                          : "Abre una fila para consultar su contexto."}
                      </p>
                    </div>
                    {tab === "marketing" && (
                      <button
                        className="mg-secondary"
                        onClick={async () => {
                          try {
                            await downloadMarketing(start, end, rep);
                          } catch (e) {
                            setError((e as Error).message);
                          }
                        }}
                      >
                        <Download size={16} /> Exportar
                      </button>
                    )}
                  </div>
                  <label className="mg-search">
                    <Search size={17} />
                    <input
                      aria-label="Buscar registros"
                      placeholder="Buscar en esta vista"
                      value={query}
                      onChange={(e) => {
                        setQuery(e.target.value);
                        setPage(0);
                      }}
                    />
                  </label>
                  <div className="mg-table-scroll">
                    <table className="mg-table">
                      <thead>
                        <tr>
                          {(tab === "team"
                            ? [
                                "Visitador",
                                "Visitas",
                                "Reportes",
                                "Cobertura",
                                "Mercadeo",
                                "Asistencias",
                                "Vencidos",
                              ]
                            : tab === "marketing"
                              ? [
                                  "Institución",
                                  "Actividad",
                                  "Visitador",
                                  "Fecha",
                                  "Estado",
                                  "Asistencias",
                                ]
                              : [
                                  "Médico",
                                  "Visitador",
                                  "Fecha",
                                  "Visita",
                                  "Reporte",
                                ]
                          ).map((h) => (
                            <th key={h}>{h}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {filtered
                          .slice(page * 10, page * 10 + 10)
                          .map((r: any) => (
                            <tr key={r.id}>
                              {tab === "team" ? (
                                <>
                                  <td>
                                    <button
                                      className="mg-table-link"
                                      onClick={() => {
                                        setRep(r.id);
                                        setTab("overview");
                                      }}
                                    >
                                      {r.name}
                                    </button>
                                  </td>
                                  <td>{r.finished}</td>
                                  <td>{r.reports}</td>
                                  <td>
                                    {r.covered} / {r.panel}
                                  </td>
                                  <td>{r.marketing}</td>
                                  <td>{r.attendances}</td>
                                  <td>{r.overdue}</td>
                                </>
                              ) : tab === "marketing" ? (
                                <>
                                  <td>
                                    <a
                                      href={`/territorio/?module=marketing&activity=${r.id}`}
                                    >
                                      {r.institution} <ArrowUpRight size={12} />
                                    </a>
                                  </td>
                                  <td>{r.kind}</td>
                                  <td>{r.representative}</td>
                                  <td>{humanDate(r.at)}</td>
                                  <td>
                                    <span className={"mg-status " + r.status}>
                                      {activityStatuses[r.status]}
                                    </span>
                                  </td>
                                  <td>{number(r.attendances)}</td>
                                </>
                              ) : (
                                <>
                                  <td>
                                    <a href={`/territorio/?report=${r.id}`}>
                                      {r.doctor} <ArrowUpRight size={12} />
                                    </a>
                                  </td>
                                  <td>{r.representative}</td>
                                  <td>{humanDate(r.at)}</td>
                                  <td>
                                    {r.finished
                                      ? "Terminada"
                                      : r.status === "not_done"
                                        ? "No realizada"
                                        : r.status === "scheduled"
                                          ? "Programada"
                                          : "En proceso"}
                                  </td>
                                  <td>
                                    <span
                                      className={
                                        "mg-status " +
                                        (r.report_status === "confirmed"
                                          ? "completed"
                                          : "draft")
                                      }
                                    >
                                      {r.report_status === "confirmed"
                                        ? "Confirmado"
                                        : "Pendiente"}
                                    </span>
                                  </td>
                                </>
                              )}
                            </tr>
                          ))}
                      </tbody>
                    </table>
                  </div>
                  {!filtered.length && (
                    <div className="mg-chart-empty">
                      No hay registros con estos filtros.
                    </div>
                  )}
                  <div className="mg-pagination">
                    <span>{filtered.length} registros</span>
                    <button disabled={!page} onClick={() => setPage(page - 1)}>
                      Anterior
                    </button>
                    <span>{page + 1}</span>
                    <button
                      disabled={(page + 1) * 10 >= filtered.length}
                      onClick={() => setPage(page + 1)}
                    >
                      Siguiente
                    </button>
                  </div>
                </section>
              )}
              <section className="mg-assistant">
                <div className="mg-assistant-intro">
                  <div className="mg-eyebrow">
                    <Sparkles size={14} /> ASISTENTE DE GERENCIA
                  </div>
                  <h2>Convierte las señales en acciones.</h2>
                  <p>
                    Consulta el período seleccionado. El asistente analiza los
                    indicadores autorizados y propone próximos pasos.
                  </p>
                </div>
                <div className="mg-assistant-chat">
                  <div className="mg-question-chips">
                    {[
                      "¿Qué debo priorizar hoy?",
                      "¿Qué falta para mejorar la cobertura?",
                      "Resume los resultados de mercadeo",
                    ].map((q) => (
                      <button
                        key={q}
                        disabled={asking}
                        onClick={() => {
                          setQuestion(q);
                          ask(q);
                        }}
                      >
                        {q}
                      </button>
                    ))}
                  </div>
                  <form
                    onSubmit={(e) => {
                      e.preventDefault();
                      ask();
                    }}
                  >
                    <input
                      aria-label="Pregunta al asistente de gerencia"
                      maxLength={1000}
                      value={question}
                      onChange={(e) => setQuestion(e.target.value)}
                      placeholder="Pregunta sobre los datos de este período"
                    />
                    <button
                      aria-label="Enviar pregunta"
                      disabled={asking || question.trim().length < 5}
                    >
                      <Send size={18} />
                    </button>
                  </form>
                  {asking && <p role="status">Analizando los indicadores…</p>}
                  {aiError && (
                    <p className="mg-error" role="alert">
                      {aiError}
                    </p>
                  )}
                  {answer && (
                    <div className="mg-answer">
                      {answer.notice&&<p className="mg-answer-notice">{answer.notice}</p>}
                      <p>{answer.answer}</p>
                      {answer.actions?.map((a:any)=><a className="mg-secondary" key={a.href} href={a.href}>{a.label} <ArrowUpRight size={14}/></a>)}
                      <small>
                        Datos al {humanDate(answer.as_of)} · Sugerencias, sin
                        cambios automáticos en la operación.
                      </small>
                    </div>
                  )}
                </div>
              </section>
              <details className="mg-definitions">
                <summary>
                  Cómo se calculan los indicadores y de dónde vienen
                </summary>
                {Object.entries(data.definitions).map(([key, value]) => (
                  <p key={key}>{String(value)}</p>
                ))}
                <div className="mg-source-grid">
                  {data.sources.map((s: any) => (
                    <div key={s.name}>
                      <b>{s.name}</b>
                      <p>{s.status}</p>
                    </div>
                  ))}
                </div>
              </details>
            </>
          )}
        </main>
      </div>
    </div>
  );
}
