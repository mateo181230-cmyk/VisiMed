import { LearningPanel } from "./Learning";
import {SourceFiles} from './Reference';
import { useEffect, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  CheckCircle2,
  Clock,
  ListChecks,
  RefreshCw,
  Search,
  Upload,
  Navigation,
} from "lucide-react";
import { api, ApiError, db, flush, libraryFile, send, type User } from "./api";
import "./workflows.css";

const owners: any = {
  representative: "Visitador",
  doctor: "Médico",
  unknown: "Por acordar",
};
const states: any = {
  open: "Pendiente",
  in_progress: "En curso",
  done: "Cumplido",
  cancelled: "Cancelado",
  superseded: "Reemplazado",
};
const docStates: any = {
  draft: "Por aprobar",
  approved: "Aprobado",
  withdrawn: "Retirado",
};
const time = (s: string) =>
  new Date(s).toLocaleTimeString("es-CO", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "America/Bogota",
  });
async function cached(path: string, user: User) {
  const key = "workflow:" + user.id + ":" + path;
  try {
    const data = await api(path);
    await db.snapshots.put({ id: key, data });
    return data;
  } catch (e) {
    if (e instanceof ApiError) throw e;
    const old = await db.snapshots.get(key);
    if (old) return { ...old.data, cached: true };
    throw e;
  }
}
function Frame({ title, subtitle, children }: any) {
  return (
    <main className="wf-shell">
      <header className="wf-top">
        <a href="/territorio/">
          <ArrowLeft size={18} /> Mi ruta
        </a>
        <strong>
          VisiMed <span>· SNC</span>
        </strong>
      </header>
      <p className="wf-eyebrow">OPERACIÓN DE CAMPO</p>
      <h1>{title}</h1>
      <p className="wf-lead">{subtitle}</p>
      {children}
      <nav className="wf-nav">
        <a href="/territorio/">Ruta</a>
        <a href="/territorio/?module=tasks">Pendientes</a>
        <a href="/territorio/?module=library">Biblioteca</a>
      </nav>
    </main>
  );
}
function Feedback({ error, note }: any) {
  return (
    <>
      {error && (
        <p role="alert" className="wf-alert error">
          {error}
        </p>
      )}
      {note && (
        <p role="status" className="wf-alert">
          {note}
        </p>
      )}
    </>
  );
}

export function TaskScreen({ user }: { user: User }) {
  const [tasks, setTasks] = useState<any[]>([]),
    [query, setQuery] = useState(""),
    [filter, setFilter] = useState("pending"),
    [page, setPage] = useState(0),
    [edit, setEdit] = useState<any>(null),
    [error, setError] = useState(""),
    [note, setNote] = useState(""),
    [busy, setBusy] = useState(false),
    [reps, setReps] = useState<any[]>([]),
    [rep, setRep] = useState(
      new URLSearchParams(location.search).get("rep") || user.id,
    ),
    [canEdit, setCanEdit] = useState(false);
  const load = async () => {
    try {
      const s = await cached("/state", user);
      setReps(s.representatives);
      setCanEdit(s.can_edit !== false);
      const chosen = s.representatives.some((r: any) => r.id === rep)
        ? rep
        : s.representative_id;
      if (chosen !== rep) {
        setRep(chosen);
        return;
      }
      await flush(user);
      const d = await cached("/tasks?representative_id=" + chosen, user);
      setTasks(d.tasks);
      if (d.cached) setNote("Sin conexión: ves la última lista descargada.");
    } catch (e: any) {
      setError(e.message);
    }
  };
  useEffect(() => {
    load();
    const timer = setInterval(load, 15000);
    return () => clearInterval(timer);
  }, [rep]);
  const filtered = tasks.filter(
    (t) =>
      (filter === "all" ||
        (filter === "pending" && ["open", "in_progress"].includes(t.status)) ||
        (filter === "overdue" && t.overdue) ||
        filter === t.status) &&
      `${t.action} ${t.doctor}`.toLowerCase().includes(query.toLowerCase()),
  );
  const save = async () => {
    setBusy(true);
    setError("");
    try {
      const r = await send(
        user,
        "task.update",
        {
          id: edit.id,
          status: edit.status,
          due_on: edit.due_on || null,
          owner: edit.owner,
          evidence: edit.evidence,
        },
        edit.version,
      );
      setNote(
        r.queued
          ? "Cambio guardado en este celular; pendiente de sincronizar."
          : "Compromiso actualizado.",
      );
      if (!r.queued) await load();
      setEdit(null);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Frame
      title="Que nada quede pendiente."
      subtitle="Compromisos confirmados, conectados con la visita que les dio origen."
    >
      <Feedback error={error} note={note} />
      {user.role !== "rep" && (
        <label>
          Visitador
          <select
            value={rep}
            onChange={(e) => {
              setRep(e.target.value);
              setPage(0);
            }}
          >
            {reps.map((r) => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </select>
        </label>
      )}
      <div className="wf-stats">
        <div>
          <b>
            {
              tasks.filter((t) => ["open", "in_progress"].includes(t.status))
                .length
            }
          </b>
          <span>Por resolver</span>
        </div>
        <div>
          <b>{tasks.filter((t) => t.overdue).length}</b>
          <span>Vencidos</span>
        </div>
        <div>
          <b>{tasks.filter((t) => t.due_today).length}</b>
          <span>Para hoy</span>
        </div>
      </div>
      <div className="wf-controls">
        <label className="wf-search">
          <Search size={18} />
          <input
            aria-label="Buscar compromisos"
            placeholder="Médico o compromiso"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setPage(0);
            }}
          />
        </label>
        <select
          aria-label="Estado del compromiso"
          value={filter}
          onChange={(e) => {
            setFilter(e.target.value);
            setPage(0);
          }}
        >
          <option value="pending">Pendientes</option>
          <option value="overdue">Vencidos</option>
          <option value="done">Cumplidos</option>
          <option value="all">Todos</option>
        </select>
      </div>
      {!filtered.length && (
        <div className="wf-empty">
          <ListChecks />
          <h2>No hay compromisos en esta vista.</h2>
          <p>
            Al confirmar un reporte, sus compromisos explícitos aparecen aquí.
            No se crean tareas a partir de suposiciones.
          </p>
        </div>
      )}
      {filtered.slice(page * 8, page * 8 + 8).map((t) => (
        <article key={t.id} className="wf-card">
          <div className="wf-row">
            <span className={"wf-badge " + (t.overdue ? "amber" : "")}>
              {t.overdue ? "Vencido" : states[t.status]}
            </span>
            <small>{t.due_on || "Sin fecha acordada"}</small>
          </div>
          <h2>{t.action}</h2>
          <p>{t.doctor}</p>
          <p className="wf-sub">
            Responsable del compromiso: {owners[t.owner]}. Seguimiento:
            visitador.
          </p>
          {t.next_objective && <p>Próximo objetivo: {t.next_objective}</p>}
          {t.evidence && <blockquote>{t.evidence}</blockquote>}
          <div className="wf-actions">
            <a href={"/territorio/?report=" + t.visit_id}>
              Ver reporte de origen <ArrowRight size={14} />
            </a>
            {canEdit && t.status !== "superseded" && (
              <button onClick={() => setEdit({ ...t })}>Actualizar</button>
            )}
          </div>
        </article>
      ))}
      <div className="wf-row">
        <button disabled={!page} onClick={() => setPage(page - 1)}>
          Anterior
        </button>
        <span>{filtered.length} resultados</span>
        <button
          disabled={(page + 1) * 8 >= filtered.length}
          onClick={() => setPage(page + 1)}
        >
          Siguiente
        </button>
      </div>
      {edit && (
        <section className="wf-editor" aria-label="Actualizar compromiso">
          <h2>{edit.action}</h2>
          <label>
            Responsable
            <select
              value={edit.owner}
              onChange={(e) => setEdit({ ...edit, owner: e.target.value })}
            >
              {Object.entries(owners).map(([k, v]: any) => (
                <option key={k} value={k}>
                  {v}
                </option>
              ))}
            </select>
          </label>
          <label>
            Fecha acordada
            <input
              type="date"
              value={edit.due_on || ""}
              onChange={(e) => setEdit({ ...edit, due_on: e.target.value })}
            />
          </label>
          <label>
            Estado
            <select
              value={edit.status}
              onChange={(e) => setEdit({ ...edit, status: e.target.value })}
            >
              {Object.entries(states)
                .filter(([k]) => k !== "superseded")
                .map(([k, v]: any) => (
                  <option key={k} value={k}>
                    {v}
                  </option>
                ))}
            </select>
          </label>
          <label>
            Evidencia o nota de seguimiento
            <textarea
              placeholder="Qué ocurrió, cuándo y cómo lo verificaste"
              value={edit.evidence}
              onChange={(e) => setEdit({ ...edit, evidence: e.target.value })}
            />
          </label>
          <Feedback error={error} />
          <div className="wf-actions">
            <button disabled={busy} onClick={() => setEdit(null)}>
              Cancelar
            </button>
            <button disabled={busy} className="wf-primary" onClick={save}>
              Guardar seguimiento
            </button>
          </div>
        </section>
      )}
    </Frame>
  );
}

export function LibraryScreen({ user }: { user: User }) {
  const params = new URLSearchParams(location.search);
  const [data, setData] = useState<any>({ documents: [], can_manage: false }),
    [selected, setSelected] = useState(params.get("document") || ""),
    [doc, setDoc] = useState<any>(null),
    [slide, setSlide] = useState(Number(params.get("slide")) || 1),
    [query, setQuery] = useState(""),
    [results, setResults] = useState<any>(null),
    [error, setError] = useState(""),
    [note, setNote] = useState(""),
    [busy, setBusy] = useState(false),
    [checked, setChecked] = useState(false),
    [reviewNote, setReviewNote] = useState(""),
    [editing, setEditing] = useState(false),
    [text, setText] = useState(""),
    [line, setLine] = useState("");
  const load = async () => {
    try {
      const d = await cached("/library", user);
      setData(d);
      if (d.cached)
        setNote("Copia sin conexión. La vigencia se verifica al reconectar.");
      if (d.can_manage) {
        const s = await cached("/state", user);
        setLine(s.products[0]?.line_id || "");
      }
    } catch (e: any) {
      setError(e.message);
    }
  };
  useEffect(() => {
    load();
  }, []);
  useEffect(() => {
    if (!selected) {
      setDoc(null);
      return;
    }
    setError("");
    setChecked(false);
    setEditing(false);
    cached("/library/" + selected, user)
      .then((d) => {
        setDoc(d);
        if (d.cached)
          setNote(
            "Material guardado sin conexión; verifica su vigencia al volver a conectarte.",
          );
      })
      .catch((e) => setError(e.message));
  }, [selected]);
  const refresh = async () => {
    await load();
    if (selected) setDoc(await api("/library/" + selected));
  };
  const review = async (status: string) => {
    setBusy(true);
    setError("");
    try {
      if (!navigator.onLine)
        throw new Error("Conéctate para revisar y publicar esta versión.");
      const r = await send(
        user,
        "knowledge.review",
        { id: doc.id, status, note: reviewNote, reviewed_visuals: checked },
        doc.revision,
      );
      setNote(
        r.queued
          ? "Revisión pendiente de sincronizar."
          : "Estado del material actualizado.",
      );
      if (!r.queued) await refresh();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  const upload = async (file?: File) => {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      if (file.size > 20 * 1024 * 1024) throw new Error("El máximo es 20 MB.");
      const d = await libraryFile(
        "import?filename=" + encodeURIComponent(file.name) + "&line_id=" + line,
        file,
      );
      setNote(
        "Presentación importada. Revisa el texto, las figuras y el OCR antes de aprobar.",
      );
      await load();
      setSelected(d.id);
      setSlide(1);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  const search = async () => {
    setError("");
    try {
      setResults(await api("/library/search?q=" + encodeURIComponent(query)));
    } catch (e: any) {
      setError(e.message);
    }
  };
  const current =
    doc?.slides.find((s: any) => s.number === slide) || doc?.slides[0];
  return (
    <Frame
      title="Biblioteca y preparación SNC."
      subtitle="Material de referencia con versión, diapositiva y aprobación identificables."
    >
      <Feedback error={error} note={note} />
      <details className="wf-source-documents"><summary>Consultar archivos originales y guías de operación</summary><SourceFiles/></details>
      <div className="wf-controls">
        <label className="wf-search">
          <Search size={18} />
          <input
            aria-label="Consultar material SNC"
            placeholder="Marca, molécula o tema"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && search()}
          />
        </label>
        <button
          className="wf-primary"
          onClick={search}
          disabled={query.trim().length < 2}
        >
          Buscar
        </button>
      </div>
      {results && (
        <section className="wf-card">
          <h2>{results.message}</h2>
          {results.sources.map((r: any) => (
            <button
              className="wf-result"
              key={r.document_id + ":" + r.slide}
              onClick={() => {
                setSelected(r.document_id);
                setSlide(r.slide);
              }}
            >
              <strong>{r.title}</strong>
              <span>
                v{r.version} · Diapositiva {r.slide}
              </span>
              <p>{r.excerpt}</p>
            </button>
          ))}
        </section>
      )}
      {data.can_manage && (
        <div className="wf-upload">
          <Upload size={18} />
          <label>
            {busy ? "Procesando presentación…" : "Importar presentación SNC"}
            <input
              type="file"
              accept=".pptx"
              disabled={busy || !line}
              onChange={(e) => upload(e.target.files?.[0])}
            />
          </label>
        </div>
      )}
      {!doc && (
        <div className="wf-library-list">
          {!data.documents.length && (
            <div className="wf-empty">
              <BookOpen />
              <h2>El material está pendiente de aprobación.</h2>
              <p>
                Gerencia revisa las presentaciones antes de habilitarlas para el
                equipo.
              </p>
            </div>
          )}
          {data.documents.map((d: any) => (
            <button
              className="wf-card"
              key={d.id}
              onClick={() => {
                setSelected(d.id);
                setSlide(1);
              }}
            >
              <BookOpen size={24} />
              <h2>{d.title}</h2>
              <div className="wf-row">
                <span className="wf-badge">{docStates[d.status]}</span>
                <span>
                  v{d.version} · {d.slide_count} diapositivas
                </span>
              </div>
              {d.ocr_count > 0 && <p>{d.ocr_count} diapositivas con OCR</p>}
            </button>
          ))}
        </div>
      )}
      {doc && (
        <section className="wf-document">
          <div className="wf-actions">
            <button onClick={() => setSelected("")}>
              ← Todos los materiales
            </button>
            <button
              disabled={busy}
              onClick={async () => {
                try {
                  const blob = await libraryFile(doc.id + "/original");
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement("a");
                  a.href = url;
                  a.download = doc.filename;
                  a.click();
                  setTimeout(() => URL.revokeObjectURL(url), 1000);
                } catch (e: any) {
                  setError(e.message);
                }
              }}
            >
              Descargar original
            </button>
          </div>
          <h2>{doc.title}</h2>
          <p>
            <span className="wf-badge">{docStates[doc.status]}</span> Versión{" "}
            {doc.version} · Revisión {doc.revision}
          </p>
          <div className="wf-row">
            <button
              disabled={slide <= 1}
              onClick={() => {
                setSlide(slide - 1);
                setEditing(false);
              }}
            >
              Anterior
            </button>
            <label>
              Diapositiva
              <select
                value={current?.number || 1}
                onChange={(e) => {
                  setSlide(Number(e.target.value));
                  setEditing(false);
                }}
              >
                {doc.slides.map((s: any) => (
                  <option key={s.number} value={s.number}>
                    {s.number} de {doc.slide_count}
                  </option>
                ))}
              </select>
            </label>
            <button
              disabled={slide >= doc.slide_count}
              onClick={() => {
                setSlide(slide + 1);
                setEditing(false);
              }}
            >
              Siguiente
            </button>
          </div>
          {current && (
            <article className="wf-card wf-slide">
              <p className="wf-eyebrow">
                DIAPOSITIVA {current.number} ·{" "}
                {current.method === "ocr"
                  ? "TEXTO OCR"
                  : current.method === "reviewed"
                    ? "TEXTO REVISADO"
                    : "TEXTO EXTRAÍDO"}
              </p>
              {editing ? (
                <textarea
                  aria-label="Corregir texto de diapositiva"
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                />
              ) : (
                <p className="wf-source-text">
                  {current.text ||
                    "No se pudo extraer texto. Revisa el original y transcribe el contenido antes de aprobar."}
                </p>
              )}
              {current.notes && (
                <details>
                  <summary>Notas del material</summary>
                  <p className="wf-source-text">{current.notes}</p>
                </details>
              )}
              {current.has_images && (
                <small>
                  La diapositiva contiene figuras. Consulta el original para
                  verlas en su contexto.
                </small>
              )}
              {data.can_manage &&
                doc.status === "draft" &&
                (editing ? (
                  <button
                    disabled={busy}
                    onClick={async () => {
                      setBusy(true);
                      try {
                        await send(
                          user,
                          "knowledge.slide",
                          { id: doc.id, number: current.number, text },
                          doc.revision,
                        );
                        await refresh();
                        setEditing(false);
                      } catch (e: any) {
                        setError(e.message);
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    Guardar corrección
                  </button>
                ) : (
                  <button
                    onClick={() => {
                      setText(current.text);
                      setEditing(true);
                    }}
                  >
                    Corregir extracción
                  </button>
                ))}
            </article>
          )}
          {data.can_manage && (
            <div className="wf-card">
              <h3>Revisión de contenido</h3>
              <label className="wf-check">
                <input
                  type="checkbox"
                  checked={checked}
                  onChange={(e) => setChecked(e.target.checked)}
                />
                Revisé el original, las figuras y el texto extraído, incluido el
                OCR.
              </label>
              <label>
                Nota de revisión
                <textarea
                  placeholder="Criterio de aprobación, correcciones o motivo de retiro"
                  value={reviewNote}
                  onChange={(e) => setReviewNote(e.target.value)}
                />
              </label>
              <div className="wf-actions">
                <button disabled={busy} onClick={() => review("draft")}>
                  Volver a borrador
                </button>
                <button disabled={busy} onClick={() => review("withdrawn")}>
                  Retirar
                </button>
                <button
                  className="wf-primary"
                  disabled={busy || !checked || reviewNote.trim().length < 8}
                  onClick={() => review("approved")}
                >
                  Aprobar esta versión
                </button>
              </div>
            </div>
          )}
          {doc.reviewed_at && (
            <p className="wf-sub">
              Revisado el{" "}
              {new Date(doc.reviewed_at).toLocaleDateString("es-CO")}.{" "}
              {doc.review_note}
            </p>
          )}
        </section>
      )}
    </Frame>
  );
}

export function BriefScreen({ user, id }: { user: User; id: string }) {
  const [data, setData] = useState<any>(null),
    [error, setError] = useState("");
  useEffect(() => {
    cached("/visit-brief/" + id, user)
      .then(setData)
      .catch((e) => setError(e.message));
  }, [id]);
  return (
    <Frame
      title={data?.doctor || "Antes de la visita."}
      subtitle="Objetivos, resultados y seguimiento de este médico."
    >
      <Feedback
        error={error}
        note={
          data?.cached ? "Última preparación descargada; sin conexión." : ""
        }
      />
      {data && (
        <>
          <div className="wf-actions"><a className="wf-primary" href={"/visitas/" + id}>Abrir esta visita <ArrowRight size={16}/></a><a href="/territorio/?module=study">Ver otras preparaciones</a></div>
          <LearningPanel user={user} id={id}/>
          <details className="wf-card">
            <summary>Resumen previo y objetivo registrado</summary>
            <h2>
              {data.context.objective || "Sin objetivo previo registrado"}
            </h2>
            <p>{data.context.brief}</p>
            <a className="wf-primary" href={"/visitas/" + id}>
              Abrir visita en VisiMed <ArrowRight size={16} />
            </a>
          </details>
          <h2>Compromisos por retomar</h2>
          {!data.tasks.length && (
            <p>No hay compromisos confirmados pendientes con este médico.</p>
          )}
          {data.tasks.map((t: any) => (
            <article className="wf-card" key={t.id}>
              <h3>{t.action}</h3>
              <p>
                {owners[t.owner]} · {t.due_on || "Sin fecha acordada"}
              </p>
              <a href={"/territorio/?module=tasks"}>Revisar seguimiento</a>
            </article>
          ))}
          <h2>Material para preparar la conversación</h2>
          {data.sources.map((s: any) => (
            <article className="wf-card" key={s.document_id + s.slide}>
              <h3>{s.title}</h3>
              <p>{s.excerpt}</p>
              <a href={s.href}>
                Ver v{s.version} · Diapositiva {s.slide}
              </a>
            </article>
          ))}
          {!data.sources.length && (
            <p>
              No hay material aprobado relacionado con el objetivo registrado.
            </p>
          )}
          <a href="/territorio/?module=library">Consultar biblioteca SNC</a>
        </>
      )}
    </Frame>
  );
}

export function ExecutionPanel({ user, plan, day, canEdit, reload }: any) {
  const [mode, setMode] = useState(""),
    [minutes, setMinutes] = useState(15),
    [reason, setReason] = useState(""),
    [visit, setVisit] = useState(""),
    [error, setError] = useState(""),
    [note, setNote] = useState(""),
    [busy, setBusy] = useState(false);
  const stops = plan.stops.filter(
    (s: any) => !s.rescheduled && s.status !== "not_done",
  );
  const next =
    stops.find((s: any) => s.status === "in_progress") ||
    stops.find((s: any) => s.status === "scheduled");
  const today = new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/Bogota",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
  const save = async () => {
    setBusy(true);
    setError("");
    try {
      const result = await send(
        user,
        "route.incident",
        {
          plan_id: plan.id,
          kind: mode,
          reason,
          visit_id: mode === "delay" ? null : visit,
          resume_at:
            mode === "delay"
              ? new Date(Date.now() + minutes * 60000).toISOString()
              : null,
        },
        plan.version,
      );
      setNote(
        result.queued
          ? "Novedad guardada en este celular; el recálculo requiere conexión."
          : "Novedad registrada. Se está recalculando lo pendiente; la ruta anterior sigue visible hasta publicar la nueva.",
      );
      setMode("");
      await reload();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="wf-execution">
      <Feedback error={error} note={note} />
      {next ? (
        <div className="wf-next">
          <div>
            <p className="wf-eyebrow">
              {next.status === "in_progress" ? "EN VISITA" : "SIGUIENTE PARADA"}{" "}
              · {time(next.scheduled_at || next.arrival_at)}
            </p>
            <h2>{next.label}</h2>
            <p>{next.reason}</p>
            <div className="wf-actions">
              {next.kind === "doctor" && (
                <a href={"/territorio/?module=brief&visit=" + next.visit_id}>
                  Preparar visita <ArrowRight size={15} />
                </a>
              )}
              {next.kind === "marketing" && <a href={"/territorio/?module=marketing&activity="+next.target_id}>Abrir actividad <ArrowRight size={15}/></a>}
              <a
                href={`https://www.google.com/maps/dir/?api=1&destination=${next.lat},${next.lng}&travelmode=driving`}
                target="_blank"
                rel="noreferrer"
              >
                <Navigation size={15} /> Navegar
              </a>
            </div>
          </div>
        </div>
      ) : (
        <p>No quedan paradas pendientes en esta versión.</p>
      )}
      {canEdit && day === today && (
        <div className="wf-actions">
          <button onClick={() => setMode("delay")}>
            <Clock size={16} /> Registrar demora
          </button>
          <button
            onClick={() => {
              setMode("not_attended");
              setVisit(next?.visit_id || "");
            }}
          >
            No atención / cancelación
          </button>
        </div>
      )}
      {mode && (
        <div className="wf-card">
          <h3>
            {mode === "delay"
              ? "¿Cuándo podrás continuar?"
              : "¿Qué ocurrió con la visita?"}
          </h3>
          {mode === "delay" ? (
            <label>
              Minutos de demora
              <select
                value={minutes}
                onChange={(e) => setMinutes(Number(e.target.value))}
              >
                {[5, 10, 15, 20, 30, 45, 60, 90, 120].map((n) => (
                  <option key={n} value={n}>
                    {n} minutos
                  </option>
                ))}
              </select>
            </label>
          ) : (
            <>
              <label>
                Visita
                <select
                  value={visit}
                  onChange={(e) => setVisit(e.target.value)}
                >
                  <option value="">Selecciona una visita</option>
                  {stops
                    .filter((s: any) => s.status === "scheduled" && s.kind !== "marketing")
                    .map((s: any) => (
                      <option key={s.visit_id} value={s.visit_id}>
                        {s.label}
                      </option>
                    ))}
                </select>
              </label>
              <label>
                Motivo
                <select value={mode} onChange={(e) => setMode(e.target.value)}>
                  <option value="not_attended">No atendieron</option>
                  <option value="cancel">Cancelación de la sede</option>
                </select>
              </label>
            </>
          )}
          <label>
            Detalle
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Describe brevemente lo ocurrido"
            />
          </label>
          <div className="wf-actions">
            <button onClick={() => setMode("")}>Volver</button>
            <button
              className="wf-primary"
              disabled={
                busy || reason.trim().length < 5 || (mode !== "delay" && !visit)
              }
              onClick={save}
            >
              <RefreshCw size={15} /> Registrar y ajustar ruta
            </button>
          </div>
        </div>
      )}
      {plan.metrics.changes?.length > 0 && (
        <details>
          <summary>
            Cambios frente a la versión {plan.metrics.previous_version} (
            {plan.metrics.changes.length})
          </summary>
          {plan.metrics.changes.map((c: any, i: number) => (
            <p key={i}>
              <strong>{c.label}</strong>:{" "}
              {c.kind === "moved"
                ? `${time(c.from)} → ${time(c.to)}`
                : c.kind === "added"
                  ? "Incorporada"
                  : "Retirada del recorrido pendiente"}
            </p>
          ))}
        </details>
      )}
      <a
        className="wf-task-link"
        href={"/territorio/?module=tasks&rep=" + plan.representative_id}
      >
        <ListChecks size={17} /> Ver compromisos y recordatorios
      </a>
    </section>
  );
}
