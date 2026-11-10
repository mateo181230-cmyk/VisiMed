import { useEffect, useState } from "react";
import {
  ArrowLeft,
  CalendarDays,
  Check,
  ChevronRight,
  Download,
  MapPin,
  Megaphone,
  Plus,
  Search,
  Trash2,
  Users,
  WifiOff,
} from "lucide-react";
import { api, ApiError, db, send, type User } from "./api";
import "./management.css";

export const activityStatuses: Record<string, string> = {
  draft: "Borrador",
  scheduled: "Programada",
  in_progress: "En curso",
  completed: "Realizada",
  cancelled: "Cancelada",
  queued: "Por sincronizar",
};
const kinds: Record<string, string> = {
  emergency: "Toma de urgencias",
  training: "Capacitación",
  roundtable: "Mesa de trabajo",
  institutional: "Encuentro institucional",
  other: "Otra actividad",
};
const consultations: Record<string, string> = {
  eps: "EPS",
  prepaid: "Prepagada",
  private: "Particular",
  complementary: "Complementario",
  institutional: "Institucional",
};
export function localDateTime(value: string) {
  return new Date(value)
    .toLocaleString("sv-SE", { timeZone: "America/Bogota" })
    .replace(" ", "T")
    .slice(0, 16);
}
export function humanDate(value: string) {
  return new Date(value).toLocaleString("es-CO", {
    timeZone: "America/Bogota",
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}
export async function downloadMarketing(start: string, end: string, rep = "") {
  const data = await api(
    `/marketing/export?start=${start}&end=${end}${rep ? "&representative_id=" + rep : ""}`,
  );
  const url = URL.createObjectURL(
    new Blob([data.content], { type: "text/csv;charset=utf-8" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = data.filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function draftFrom(row: any, cat: any) {
  if (row)
    return {
      id: row.id,
      representative_id: row.representative_id,
      line_id: row.line_id,
      institution_id: row.institution_id,
      status: row.status,
      kind: row.kind,
      objective: row.objective,
      starts_at: localDateTime(row.starts_at),
      ends_at: localDateTime(row.ends_at),
      planned_attendees: row.data.planned_attendees,
      product_ids: row.data.products.map((x: any) => x.id),
      consultation_types: row.data.consultation_types,
      attendees: row.data.attendees,
      materials: row.data.materials,
      outcome: row.data.outcome || "",
      next_action: row.data.next_action || "",
      cancellation_reason: row.data.cancellation_reason || "",
    };
  const day = localDateTime(
    new Date(Date.now() + 86400000).toISOString(),
  ).slice(0, 10);
  return {
    id: crypto.randomUUID(),
    representative_id: cat.representative_id,
    line_id: cat.lines[0]?.id || "",
    institution_id: "",
    status: "draft",
    kind: "training",
    objective: "",
    starts_at: day + "T09:00",
    ends_at: day + "T10:00",
    planned_attendees: 5,
    product_ids: [],
    consultation_types: [],
    attendees: [],
    materials: [],
    outcome: "",
    next_action: "",
    cancellation_reason: "",
  };
}

export function MarketingScreen({ user }: { user: User }) {
  const [catalog, setCatalog] = useState<any>(null),
    [rep, setRep] = useState(""),
    [data, setData] = useState<any>({ items: [], total: 0 }),
    [query, setQuery] = useState(""),
    [status, setStatus] = useState("all"),
    [page, setPage] = useState(0),
    [editor, setEditor] = useState<any>(null),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false),
    [pending, setPending] = useState<any[]>([]),
    [cached, setCached] = useState(false);
  const load = async () => {
    const key = `marketing:${user.id}:${rep}:${query}:${status}:${page}`;
    try {
      const c = await api(
        "/marketing/catalog" + (rep ? "?representative_id=" + rep : ""),
      );
      setCatalog(c);
      await db.snapshots.put({
        id: `marketing-catalog:${user.id}:${rep}`,
        data: c,
      });
      const d = await api(
        `/marketing/activities?offset=${page * 12}&q=${encodeURIComponent(query)}&status=${status}${rep ? "&representative_id=" + rep : ""}`,
      );
      setData(d);
      await db.snapshots.put({ id: key, data: d });
      setCached(false);
      setError("");
    } catch (e) {
      if (e instanceof ApiError) {
        setError(e.message);
        setData({ items: [], total: 0 });
        setCatalog(null);
        return;
      }
      const old = await db.snapshots.get(key);
      const c = await db.snapshots.get(`marketing-catalog:${user.id}:${rep}`);
      if (old && c) {
        setData(old.data);
        setCatalog(c.data);
        setCached(true);
      } else setError((e as Error).message);
    }
    setPending(
      (await db.commands.where("actor_id").equals(user.id).toArray()).filter(
        (x) => x.type === "marketing.save",
      ),
    );
  };
  useEffect(() => {
    load();
    const timer = setInterval(() => {
      if (document.visibilityState === "visible" && !editor) load();
    }, 20000);
    return () => clearInterval(timer);
  }, [rep, query, status, page, editor]);
  useEffect(() => {
    const id = new URLSearchParams(location.search).get("activity");
    if (id)
      api("/marketing/activities/" + id)
        .then(async (row) => {
          const c = await api(
            "/marketing/catalog?representative_id=" + row.representative_id,
          );
          setCatalog(c);
          setEditor({ row, form: draftFrom(row, c) });
        })
        .catch((e) => setError(e.message));
  }, []);
  async function create() {
    if (!catalog) return;
    const saved = await db.snapshots.get(`marketing-draft:${user.id}:new`);
    const form=saved?.data?.form || draftFrom(null,catalog);
    if(form.representative_id!==catalog.representative_id){
      try{setCatalog(await api("/marketing/catalog?representative_id="+form.representative_id))}
      catch(e){setError((e as Error).message);return}
    }
    setEditor({ row: null, form });
  }
  async function edit(row: any) {
    try {
      if(!cached) row=await api("/marketing/activities/"+row.id);
      const c = cached && catalog.representative_id === row.representative_id ? catalog : await api(
        "/marketing/catalog?representative_id=" + row.representative_id,
      );
      setCatalog(c);
      const saved = await db.snapshots.get(
        `marketing-draft:${user.id}:${row.id}`,
      );
      setEditor({ row, form: saved?.data?.version===row.version?saved.data.form:draftFrom(row, c) });
    } catch (e) {
      setError((e as Error).message);
    }
  }
  if (editor && catalog)
    return (
      <ActivityEditor
        user={user}
        initial={editor}
        catalog={catalog}
        close={() => {
          setEditor(null);
          load();
        }}
        saved={(message) => {
          setNotice(message);
          setEditor(null);
          load();
        }}
      />
    );
  return (
    <div className="mg-shell mobile-work">
      <header className="mg-header">
        <a href="/territorio/" className="mg-back">
          <ArrowLeft size={20} /> Mi jornada
        </a>
        <span className="mg-wordmark">
          VisiMed<span> / Mercadeo</span>
        </span>
      </header>
      <main className="mg-main">
        <div className="mg-eyebrow">OPERACIÓN DE CAMPO · SNC</div>
        <div className="mg-title-row">
          <div>
            <h1>Actividades de mercadeo</h1>
            <p>De la preparación al resultado, en el mismo lugar.</p>
          </div>
          <button className="mg-primary" onClick={create} disabled={!catalog}>
            <Plus size={18} /> Nueva actividad
          </button>
        </div>
        {error && (
          <div className="mg-error" role="alert">
            {error}
            <button onClick={load}>Reintentar</button>
          </div>
        )}
        {notice && (
          <div className="mg-success" role="status">
            {notice}
          </div>
        )}
        {cached && (
          <p className="mg-notice">
            <WifiOff size={16} /> Datos guardados en este celular. Se
            actualizarán al recuperar conexión.
          </p>
        )}
        {!!pending.length && (
          <div className="mg-notice">
            {pending.length} actividad(es) por sincronizar.{" "}
            {pending.some((x) => x.error)
              ? "Hay una operación que necesita revisión en Mi jornada."
              : "Puedes continuar; conservamos la operación en este celular."}
          </div>
        )}
        <div className="mg-toolbar">
          <label className="mg-search">
            <Search size={17} />
            <input
              aria-label="Buscar actividades"
              placeholder="Institución u objetivo"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setPage(0);
              }}
            />
          </label>
          <select
            aria-label="Estado"
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setPage(0);
            }}
          >
            <option value="all">Todos los estados</option>
            {Object.entries(activityStatuses)
              .filter(([x]) => x !== "queued")
              .map(([v, n]) => (
                <option key={v} value={v}>
                  {n}
                </option>
              ))}
          </select>
          {user.role !== "rep" && catalog && (
            <select
              aria-label="Visitador"
              value={rep}
              onChange={(e) => {
                setRep(e.target.value);
                setPage(0);
              }}
            >
              <option value="">Todo el equipo</option>
              {catalog.representatives.map((r: any) => (
                <option key={r.id} value={r.id}>
                  {r.name}
                </option>
              ))}
            </select>
          )}
        </div>
        <div className="mg-activity-list">
          {data.items.map((a: any) => (
            <button
              className="mg-activity-row"
              key={a.id}
              onClick={() => edit(a)}
              disabled={pending.some((x) => x.payload.id === a.id)}
            >
              <div className="mg-activity-icon">
                <Megaphone size={22} />
              </div>
              <div className="mg-activity-body">
                <div className="mg-row">
                  <span className="mg-kicker">{a.kind_label}</span>
                  <span className={"mg-status " + a.status}>
                    {activityStatuses[a.status]}
                  </span>
                </div>
                <h2>{a.institution}</h2>
                <p>{a.objective}</p>
                <div className="mg-meta">
                  <span>
                    <CalendarDays size={14} />
                    {humanDate(a.starts_at)}
                  </span>
                  <span>
                    <Users size={14} />
                    {a.status === "completed"
                      ? `${a.panel_count + a.external_count} asistentes`
                      : `${a.data.planned_attendees} previstos`}
                  </span>
                </div>
                {user.role !== "rep" && <small>{a.representative}</small>}
                {a.route_message && <small>{a.route_state==="included"?"✓ ":"· "}{a.route_message}</small>}
              </div>
              <ChevronRight size={20} />
            </button>
          ))}
        </div>
        {!data.items.length && (
          <div className="mg-empty">
            <Megaphone size={32} />
            <h2>
              {query || status !== "all"
                ? "No hay actividades con estos filtros"
                : "Prepara tu primera actividad"}
            </h2>
            <p>
              Selecciona una institución, define el objetivo y las marcas. Al
              programarla, reservaremos ese espacio en tu ruta.
            </p>
            <button className="mg-primary" onClick={create} disabled={!catalog}>
              Crear actividad
            </button>
          </div>
        )}
        <div className="mg-pagination">
          <span>{data.total} actividades</span>
          <button disabled={page === 0} onClick={() => setPage(page - 1)}>
            Anterior
          </button>
          <span>{page + 1}</span>
          <button
            disabled={(page + 1) * 12 >= data.total}
            onClick={() => setPage(page + 1)}
          >
            Siguiente
          </button>
        </div>
        <button
          className="mg-quiet"
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              const end = localDateTime(new Date().toISOString()).slice(0, 10);
              const start = localDateTime(
                new Date(Date.now() - 30 * 86400000).toISOString(),
              ).slice(0, 10);
              await downloadMarketing(start, end, rep);
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          <Download size={16} /> Exportar últimos 30 días
        </button>
        <p className="mg-footnote">
          La exportación permite conciliar el registro con Pharmadvisor. No
          envía ni modifica información en ese sistema.
        </p>
      </main>
    </div>
  );
}

function ActivityEditor({
  user,
  initial,
  catalog: initialCatalog,
  close,
  saved,
}: any) {
  const [form, setForm] = useState<any>(initial.form),
    [cat, setCat] = useState(initialCatalog),
    [step, setStep] = useState(0),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [doctorSearch, setDoctorSearch] = useState(""),
    [external, setExternal] = useState({ name: "", specialty: "" }),
    [material, setMaterial] = useState({ name: "", quantity: 1 });
  const row = initial.row,
    readOnly = row && ["completed", "cancelled"].includes(row.status);
  const key = `marketing-draft:${user.id}:${row?.id || "new"}`;
  useEffect(() => {
    if (!readOnly) {
      const t = setTimeout(
        () => db.snapshots.put({ id: key, data: {form,version:row?.version||0} }),
        250,
      );
      return () => clearTimeout(t);
    }
  }, [form]);
  const field = (name: string, value: any) =>
    setForm((f: any) => ({ ...f, [name]: value }));
  const toggle = (key: string, value: string) =>
    field(
      key,
      form[key].includes(value)
        ? form[key].filter((x: string) => x !== value)
        : [...form[key], value],
    );
  const totals: Record<string, number> = {};
  form.attendees.forEach((a: any) => {
    totals[a.specialty] = (totals[a.specialty] || 0) + 1;
  });
  const submit = async (status: string) => {
    setBusy(true);
    setError("");
    try {
      if (
        !form.institution_id ||
        !form.line_id ||
        !form.product_ids.length ||
        !form.consultation_types.length ||
        form.objective.trim().length < 5
      )
        throw new Error(
          "Completa institución, objetivo, marcas y tipo de consulta en Preparación.",
        );
      if (
        !form.starts_at ||
        !form.ends_at ||
        new Date(form.ends_at + "-05:00") <= new Date(form.starts_at + "-05:00")
      )
        throw new Error("Revisa el inicio y el final de la actividad.");
      if (
        status === "completed" &&
        (!form.attendees.length || form.outcome.trim().length < 10)
      )
        throw new Error(
          "Relaciona los médicos asistentes y describe el resultado (mínimo 10 caracteres) antes de finalizar.",
        );
      const result = await send(
        user,
        "marketing.save",
        {
          ...form,
          status,
          starts_at: new Date(form.starts_at + "-05:00").toISOString(),
          ends_at: new Date(form.ends_at + "-05:00").toISOString(),
        },
        row?.version || 0,
      );
      await db.snapshots.delete(key);
      saved(
        result.queued
          ? "Actividad guardada en el celular. Pendiente de validación y sincronización; todavía no reserva la ruta."
          : result.message,
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="mg-shell mobile-work">
      <header className="mg-header">
        <button className="mg-back" onClick={close}>
          <ArrowLeft size={20} /> Actividades
        </button>
        <span className="mg-wordmark">
          VisiMed<span> / Mercadeo</span>
        </span>
      </header>
      <main className="mg-main mg-editor">
        <div className="mg-eyebrow">
          {row ? `ACTIVIDAD · VERSIÓN ${row.version}` : "NUEVA ACTIVIDAD"}
        </div>
        <h1>{readOnly ? row.institution : "Una actividad con propósito"}</h1>
        <p>
          {readOnly
            ? "Registro cerrado. Su evidencia se conserva en el historial."
            : "Prepara la actividad, registra quién asistió y cierra con el resultado."}
        </p>
        <nav className="mg-steps" aria-label="Pasos de la actividad">
          {["Preparación", "Asistentes", "Resultado"].map((name, i) => (
            <button
              className={step === i ? "selected" : ""}
              key={name}
              onClick={() => setStep(i)}
            >
              <span>{i + 1}</span>
              {name}
            </button>
          ))}
        </nav>
        {error && (
          <div className="mg-error" role="alert">
            {error}
          </div>
        )}
        {row?.route_message && <p className="mg-notice">{row.route_message}</p>}
        <fieldset disabled={readOnly || busy} className="mg-fields">
          {step === 0 && (
            <section>
              <h2>¿Dónde y para qué?</h2>
              <div className="mg-form-grid">
                {user.role !== "rep" && (
                  <label>
                    Visitador responsable
                    <select
                      value={form.representative_id}
                      disabled={!!row}
                      onChange={async (e) => {
                        try {
                          const c = await api(
                            "/marketing/catalog?representative_id=" +
                              e.target.value,
                          );
                          setCat(c);
                          setForm((f: any) => ({
                            ...f,
                            representative_id: c.representative_id,
                            institution_id: "",
                            attendees: [],
                          }));
                        } catch (e) {
                          setError((e as Error).message);
                        }
                      }}
                    >
                      {cat.representatives.map((r: any) => (
                        <option key={r.id} value={r.id}>
                          {r.name}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                <label>
                  Tipo de actividad
                  <select
                    value={form.kind}
                    onChange={(e) => field("kind", e.target.value)}
                  >
                    {Object.entries(kinds).map(([v, n]) => (
                      <option key={v} value={v}>
                        {n}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="mg-full">
                  Institución y sede
                  <select
                    value={form.institution_id}
                    onChange={(e) => field("institution_id", e.target.value)}
                  >
                    <option value="">Seleccionar institución</option>
                    {cat.sites.map((s: any) => (
                      <option key={s.id} value={s.id}>
                        {s.name} · {s.address || "Sin dirección"}
                        {s.verified ? "" : " · Verificar ubicación"}
                      </option>
                    ))}
                  </select>
                  <small>
                    <MapPin size={13} /> Al programar, esta sede entra como
                    parada fija en tu ruta.
                  </small>
                </label>
                <label>
                  Inicio · Bogotá
                  <input
                    type="datetime-local"
                    value={form.starts_at}
                    onChange={(e) => field("starts_at", e.target.value)}
                  />
                </label>
                <label>
                  Final · Bogotá
                  <input
                    type="datetime-local"
                    value={form.ends_at}
                    onChange={(e) => field("ends_at", e.target.value)}
                  />
                </label>
                <label className="mg-full">
                  Objetivo de la actividad
                  <textarea
                    rows={3}
                    placeholder="Qué buscas lograr y cómo sabrás que se consiguió"
                    value={form.objective}
                    maxLength={2000}
                    onChange={(e) => field("objective", e.target.value)}
                  />
                </label>
                <label>
                  Médicos previstos
                  <input
                    type="number"
                    min={1}
                    max={1000}
                    value={form.planned_attendees}
                    onChange={(e) =>
                      field("planned_attendees", Number(e.target.value))
                    }
                  />
                </label>
              </div>
              <h3>Marcas que vas a presentar</h3>
              <div className="mg-choices">
                {cat.products.map((p: any) => (
                  <button
                    type="button"
                    aria-pressed={form.product_ids.includes(p.id)}
                    className={
                      form.product_ids.includes(p.id) ? "selected" : ""
                    }
                    key={p.id}
                    onClick={() => toggle("product_ids", p.id)}
                  >
                    {form.product_ids.includes(p.id) && <Check size={14} />}{" "}
                    {p.name}
                  </button>
                ))}
              </div>
              <h3>Tipo de consulta</h3>
              <div className="mg-choices">
                {Object.entries(consultations).map(([id, n]) => (
                  <button
                    key={id}
                    type="button"
                    aria-pressed={form.consultation_types.includes(id)}
                    className={
                      form.consultation_types.includes(id) ? "selected" : ""
                    }
                    onClick={() => toggle("consultation_types", id)}
                  >
                    {n}
                  </button>
                ))}
              </div>
            </section>
          )}
          {step === 1 && (
            <section>
              <h2>¿Quiénes asistieron?</h2>
              <div className="mg-attendance">
                <strong>
                  {form.attendees.length}
                  <span>médicos registrados</span>
                </strong>
                <div>
                  <b>{form.attendees.filter((x: any) => x.doctor_id).length}</b>{" "}
                  del panel
                  <br />
                  <b>
                    {form.attendees.filter((x: any) => !x.doctor_id).length}
                  </b>{" "}
                  fuera del panel
                </div>
              </div>
              {!readOnly && (
                <>
                  <label>
                    Buscar en el panel
                    <input
                      placeholder="Nombre del médico"
                      value={doctorSearch}
                      onChange={(e) => setDoctorSearch(e.target.value)}
                    />
                  </label>
                  {doctorSearch.length >= 2 && (
                    <div className="mg-search-results">
                      {cat.doctors
                        .filter(
                          (d: any) =>
                            d.name
                              .toLowerCase()
                              .includes(doctorSearch.toLowerCase()) &&
                            !form.attendees.some(
                              (a: any) => a.doctor_id === d.id,
                            ),
                        )
                        .slice(0, 8)
                        .map((d: any) => (
                          <button
                            key={d.id}
                            onClick={() => {
                              field("attendees", [
                                ...form.attendees,
                                {
                                  doctor_id: d.id,
                                  name: d.name,
                                  specialty: d.specialty || "Por confirmar",
                                },
                              ]);
                              setDoctorSearch("");
                            }}
                          >
                            <Plus size={16} />
                            <span>
                              {d.name}
                              <small>{d.specialty}</small>
                            </span>
                          </button>
                        ))}
                    </div>
                  )}
                  <details className="mg-add-external">
                    <summary>Agregar médico fuera del panel</summary>
                    <p>
                      No se añadirá automáticamente al panel ni a la frecuencia
                      de visitas.
                    </p>
                    <label>
                      Nombre completo
                      <input
                        value={external.name}
                        onChange={(e) =>
                          setExternal({ ...external, name: e.target.value })
                        }
                      />
                    </label>
                    <label>
                      Especialidad
                      <input
                        value={external.specialty}
                        onChange={(e) =>
                          setExternal({
                            ...external,
                            specialty: e.target.value,
                          })
                        }
                      />
                    </label>
                    <button
                      className="mg-secondary"
                      onClick={() => {
                        if (
                          external.name.trim().length < 5 ||
                          external.specialty.trim().length < 2
                        ) {
                          setError(
                            "Completa nombre y especialidad del médico.",
                          );
                          return;
                        }
                        if (
                          form.attendees.some(
                            (a: any) =>
                              a.name.toLowerCase() ===
                              external.name.trim().toLowerCase(),
                          )
                        ) {
                          setError("Este médico ya está relacionado.");
                          return;
                        }
                        field("attendees", [
                          ...form.attendees,
                          { doctor_id: null, ...external },
                        ]);
                        setExternal({ name: "", specialty: "" });
                        setError("");
                      }}
                    >
                      Agregar asistente
                    </button>
                  </details>
                </>
              )}
              <div className="mg-people">
                {form.attendees.map((a: any, i: number) => (
                  <div className="mg-person" key={a.doctor_id || i}>
                    <div>
                      <b>{a.name}</b>
                      <small>
                        {a.doctor_id ? "En el panel" : "Fuera del panel"}
                      </small>
                      <input
                        aria-label={"Especialidad de " + a.name}
                        value={a.specialty}
                        onChange={(e) =>
                          field(
                            "attendees",
                            form.attendees.map((x: any, j: number) =>
                              i === j ? { ...x, specialty: e.target.value } : x,
                            ),
                          )
                        }
                      />
                    </div>
                    {!readOnly && (
                      <button
                        aria-label={"Quitar a " + a.name}
                        onClick={() =>
                          field(
                            "attendees",
                            form.attendees.filter(
                              (_: any, j: number) => j !== i,
                            ),
                          )
                        }
                      >
                        <Trash2 size={16} />
                      </button>
                    )}
                  </div>
                ))}
              </div>
              <div className="mg-specialties">
                {Object.entries(totals).map(([n, v]) => (
                  <span key={n}>
                    {n}
                    <b>{v}</b>
                  </span>
                ))}
              </div>
            </section>
          )}
          {step === 2 && (
            <section>
              <h2>El resultado, con evidencia</h2>
              <label>
                ¿Qué se logró?
                <textarea
                  rows={4}
                  placeholder="Resultado observado, preguntas recibidas y cómo se cumplió el objetivo"
                  value={form.outcome}
                  maxLength={3000}
                  onChange={(e) => field("outcome", e.target.value)}
                />
              </label>
              <label>
                Compromisos o siguiente acción
                <textarea
                  rows={2}
                  value={form.next_action}
                  maxLength={1000}
                  onChange={(e) => field("next_action", e.target.value)}
                />
              </label>
              <h3>Material entregado</h3>
              {!readOnly && (
                <div className="mg-material-add">
                  <input
                    aria-label="Material"
                    placeholder="Ej. ficha científica aprobada"
                    value={material.name}
                    onChange={(e) =>
                      setMaterial({ ...material, name: e.target.value })
                    }
                  />
                  <input
                    aria-label="Cantidad de material"
                    type="number"
                    min={1}
                    value={material.quantity}
                    onChange={(e) =>
                      setMaterial({
                        ...material,
                        quantity: Number(e.target.value),
                      })
                    }
                  />
                  <button
                    aria-label="Agregar material"
                    onClick={() => {
                      if (
                        material.name.trim().length > 1 &&
                        material.quantity > 0
                      ) {
                        field("materials", [...form.materials, material]);
                        setMaterial({ name: "", quantity: 1 });
                      }
                    }}
                  >
                    <Plus size={18} />
                  </button>
                </div>
              )}
              {form.materials.map((m: any, i: number) => (
                <div className="mg-row mg-material" key={i}>
                  <span>
                    {m.name} · {m.quantity} unidades
                  </span>
                  {!readOnly && (
                    <button
                      aria-label={"Quitar " + m.name}
                      onClick={() =>
                        field(
                          "materials",
                          form.materials.filter((_: any, j: number) => i !== j),
                        )
                      }
                    >
                      <Trash2 size={16} />
                    </button>
                  )}
                </div>
              ))}
              <p className="mg-notice">
                Al finalizar, {form.attendees.length} asistentes y el resultado
                aparecerán en el dashboard de gerencia. Este registro no
                equivale a una venta ni reemplaza una visita médica.
              </p>
            </section>
          )}
        </fieldset>
        {readOnly && row.history && (
          <details className="mg-history">
            <summary>Historial del registro</summary>
            {row.history.map((h: any) => (
              <p key={h.version}>
                Versión {h.version} · {activityStatuses[h.status]} ·{" "}
                {humanDate(h.at)}
              </p>
            ))}
          </details>
        )}
        {!readOnly && (
          <>
            <div className="mg-editor-actions">
              <button
                disabled={busy}
                className="mg-secondary"
                onClick={() => submit(row?.status || "draft")}
              >
                {busy ? "Guardando…" : "Guardar"}
              </button>
              {step < 2 ? (
                <button
                  className="mg-primary"
                  onClick={() => setStep(step + 1)}
                >
                  Continuar <ChevronRight size={17} />
                </button>
              ) : (
                <button
                  className="mg-primary"
                  disabled={busy}
                  onClick={() => submit("completed")}
                >
                  <Check size={17} /> Finalizar actividad
                </button>
              )}
            </div>
            <div className="mg-secondary-actions">
              {(!row || row.status === "draft") && (
                <button
                  disabled={busy}
                  className="mg-quiet"
                  onClick={() => submit("scheduled")}
                >
                  <CalendarDays size={16} /> Programar y reservar ruta
                </button>
              )}
              {row?.status === "scheduled" && (
                <button
                  disabled={busy}
                  className="mg-quiet"
                  onClick={() => submit("in_progress")}
                >
                  Iniciar actividad
                </button>
              )}
              {row && (
                <details>
                  <summary>Cancelar actividad</summary>
                  <label>
                    Motivo
                    <textarea
                      value={form.cancellation_reason}
                      onChange={(e) =>
                        field("cancellation_reason", e.target.value)
                      }
                    />
                  </label>
                  <button disabled={busy} onClick={() => submit("cancelled")}>
                    Confirmar cancelación
                  </button>
                </details>
              )}
            </div>
            <p className="mg-footnote">
              Los cambios se conservan como borrador en este celular hasta que
              los guardes. Los horarios usan la zona de Bogotá.
            </p>
          </>
        )}
      </main>
    </div>
  );
}
