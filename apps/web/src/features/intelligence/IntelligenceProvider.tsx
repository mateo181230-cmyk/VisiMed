import {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useToast } from "../../components/Toast";
import { intelligenceApi, type PilotSnapshot } from "../../api/client";
import { dateKey, localToUtc } from "../../lib/time";
import { useAuth } from "../auth/AuthProvider";
import { enqueue } from "../../sync/outbox";
import { visitScheduled } from "../../sync/events";
import { DOCTORS, RECOMMENDATIONS } from "./demoData";
import { DEMO_TODAY, REPRESENTATIVES } from "./demoData";
import {
  DEMO_STORAGE_KEY,
  initialDemoState,
  readDemoState,
  schedulingError,
} from "./model";
import { analyzePilot, type PilotAnalysis } from "./pilot";
import {
  createDemoSnapshot,
  readPilotDemo,
  PILOT_DEMO_STORAGE_KEY,
} from "./pilotDemo";
import type {
  CalendarVisit,
  DemoState,
  DoctorProfile,
  Recommendation,
} from "./types";

interface IntelligenceContextValue {
  basePath: string;
  mode: "demo" | "empty" | "live";
  setMode: (mode: "demo" | "empty" | "live") => void;
  loading: boolean;
  loadError: string | null;
  refresh: () => void;
  today: string;
  representatives: { id: string; name: string }[];
  analysis: PilotAnalysis | null;
  demoSnapshot: PilotSnapshot;
  updateDemo: (snapshot: PilotSnapshot) => void;
  scope: string;
  setScope: (scope: string) => void;
  doctors: DoctorProfile[];
  recommendations: Recommendation[];
  visits: CalendarVisit[];
  state: DemoState;
  addVisit: (visit: CalendarVisit) => Promise<string | null>;
  accept: (recommendation: Recommendation) => Promise<string | null>;
  dismiss: (id: string, reason?: string) => void;
  removeVisit: (id: string) => void;
  review: (id: string) => void;
  reset: () => void;
  path: (segment?: string) => string;
}

const Context = createContext<IntelligenceContextValue | null>(null);

export function useIntelligence(): IntelligenceContextValue {
  const value = useContext(Context);
  if (!value) throw new Error("Falta IntelligenceProvider");
  return value;
}

export function IntelligenceProvider({
  preview = false,
  children,
}: {
  preview?: boolean;
  children: ReactNode;
}) {
  const basePath = preview ? "/inteligencia/demo" : "/inteligencia";
  const [mode, setMode] = useState<"demo" | "empty" | "live">(
    preview ? "demo" : "live",
  );
  const { user } = useAuth();
  const [raw, setRaw] = useState<PilotSnapshot | null>(null);
  const [loading, setLoading] = useState(!preview);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [demoSnapshot, setDemoSnapshot] = useState(readPilotDemo);
  const [liveState, setLiveState] = useState<DemoState>({
    visits: [],
    decisions: {},
    reviewed: [],
  });
  const [scope, setScope] = useState("all");
  const [state, setState] = useState(readDemoState);
  const toast = useToast();
  const manualRefresh = useRef(false);

  useEffect(() => {
    if (preview) return;
    setRaw(null);
    setLiveState({ visits: [], decisions: {}, reviewed: [] });
    setScope("all");
  }, [preview, user?.id]);

  useEffect(() => {
    if (preview || !user) return;
    let active = true;
    setLoading(true);
    setLoadError(null);
    void intelligenceApi.snapshot().then((result) => {
      if (!active) return;
      setLoading(false);
      if (result.ok) {
        setRaw(result.data);
        setMode(current => current === 'empty' ? 'live' : current);
        if (manualRefresh.current) toast.show('Reportes actualizados.');
      } else {
        setLoadError(
          result.kind === "network"
            ? "Sin conexión. No se pudieron consultar los reportes."
            : "No se pudieron consultar los reportes. Intenta actualizar.",
        );
        setMode(current => current === 'demo' ? 'demo' : 'empty');
      }
      manualRefresh.current = false;
    });
    return () => {
      active = false;
    };
  }, [preview, user?.id, revision]);

  useEffect(() => {
    if (preview) return;
    const refresh = () => setRevision((v) => v + 1);
    window.addEventListener("focus", refresh);
    window.addEventListener("online", refresh);
    return () => {
      window.removeEventListener("focus", refresh);
      window.removeEventListener("online", refresh);
    };
  }, [preview]);

  const analysis = useMemo(
    () =>
      mode === "live" && raw
        ? analyzePilot(raw, scope)
        : mode === "demo"
          ? analyzePilot(demoSnapshot, scope)
          : null,
    [mode, raw, scope, demoSnapshot],
  );
  const today =
    mode === "live" && raw ? dateKey(raw.now, raw.timezone) : DEMO_TODAY;
  const representatives =
    mode === "live" && raw ? raw.representatives : REPRESENTATIVES;

  useEffect(() => {
    if (scope !== 'all' && (mode !== 'live' || raw) && !representatives.some(r => r.id === scope)) setScope('all');
  }, [mode, raw, scope, representatives]);

  useEffect(() => {
    try {
      sessionStorage.setItem(DEMO_STORAGE_KEY, JSON.stringify(state));
    } catch {
      /* Sin almacenamiento, sigue funcionando en memoria. */
    }
  }, [state]);

  const doctors = useMemo(
    () =>
      mode === "live"
        ? (analysis?.doctors ?? [])
        : mode === "demo"
          ? DOCTORS.filter(
              (d) => scope === "all" || d.representativeId === scope,
            ).map((d) => {
              const computed = analysis?.doctors.find((p) => p.id === d.id);
              const freshVisits =
                computed?.visits.filter((v) =>
                  v.id.startsWith("pilot-demo-"),
                ) ?? [];
              return freshVisits.length
                ? {
                    ...d,
                    visits: [...freshVisits, ...d.visits],
                    observations: [
                      ...(computed?.observations.filter((o) =>
                        o.visitId.startsWith("pilot-demo-"),
                      ) ?? []),
                      ...d.observations,
                    ],
                    profiles: computed?.profiles ?? d.profiles,
                  }
                : d;
            })
          : [],
    [mode, scope, analysis],
  );
  const doctorIds = new Set(doctors.map((d) => d.id));
  const updatedDemoProfiles = new Set(
    analysis?.doctors.flatMap((d) =>
      d.visits
        .filter((v) => v.id.startsWith("pilot-demo-") && v.confirmed)
        .map((v) => `${d.id}:${v.line}`),
    ) ?? [],
  );
  const recommendations =
    mode === "demo"
      ? [
          ...(analysis?.recommendations.filter((r) =>
            r.id.startsWith("followup-pilot-demo-"),
          ) ?? []),
          ...RECOMMENDATIONS.filter(
            (r) =>
              doctorIds.has(r.doctorId) &&
              !updatedDemoProfiles.has(`${r.doctorId}:${r.line}`),
          ),
        ]
      : mode === "live"
        ? (analysis?.recommendations ?? [])
        : [];
  const visits =
    mode === "demo"
      ? state.visits.filter((v) => doctorIds.has(v.doctorId))
      : mode === "live"
        ? [
            ...(analysis?.visits ?? []),
            ...liveState.visits.filter(
              (v) => !analysis?.visits.some((saved) => saved.id === v.id),
            ),
          ]
        : [];

  async function addVisit(visit: CalendarVisit): Promise<string | null> {
    if (mode === "live" && raw) {
      if (
        visit.recommendationId &&
        liveState.decisions[visit.recommendationId]?.status === "accepted"
      )
        return null;
      if (user?.role !== "rep")
        return "Programa la visita desde la cuenta del visitador; esta vista gerencial permite consultar al equipo.";
      const error = schedulingError(visit, visits, doctors, today);
      if (error) return error;
      const line = raw.lines.find((l) => l.code === visit.line);
      if (!line) return "No se encontró la línea de producto.";
      const id = crypto.randomUUID();
      await enqueue(
        visitScheduled(id, {
          doctor_id: visit.doctorId,
          line_ids: [line.id],
          scheduled_at: localToUtc(
            visit.day,
            visit.time,
            raw.timezone,
          ).toISOString(),
        }),
      );
      setLiveState((s) => ({
        ...s,
        visits: [...s.visits, { ...visit, id }],
        decisions: visit.recommendationId
          ? { ...s.decisions, [visit.recommendationId]: { status: "accepted" } }
          : s.decisions,
      }));
      toast.show(
        "Visita guardada en tu agenda. Se enviará cuando haya conexión.",
      );
      return null;
    }
    if (mode !== "demo")
      return "Espera a que se carguen los datos o explora la demostración.";
    if (
      visit.recommendationId &&
      state.decisions[visit.recommendationId]?.status === "accepted"
    )
      return null;
    const error = schedulingError(visit, state.visits);
    if (error) return error;
    setState((current) => {
      if (
        current.visits.some((v) => v.id === visit.id) ||
        schedulingError(visit, current.visits)
      )
        return current;
      return {
        ...current,
        visits: [...current.visits, visit],
        decisions: visit.recommendationId
          ? {
              ...current.decisions,
              [visit.recommendationId]: { status: "accepted" },
            }
          : current.decisions,
      };
    });
    toast.show("Visita agregada al calendario de ejemplo.");
    return null;
  }

  function accept(r: Recommendation): Promise<string | null> {
    return addVisit({
      id: `demo-${r.id}`,
      doctorId: r.doctorId,
      line: r.line,
      day: r.day,
      time: r.time,
      duration: r.duration,
      source: "suggestion",
      recommendationId: r.id,
    });
  }

  function dismiss(id: string, reason?: string) {
    if (mode === "live") {
      setLiveState((s) => ({
        ...s,
        decisions: { ...s.decisions, [id]: { status: "dismissed", reason } },
      }));
      toast.show("Sugerencia descartada en esta sesión.");
      return;
    }
    setState((current) =>
      current.decisions[id]?.status === "accepted"
        ? current
        : {
            ...current,
            decisions: {
              ...current.decisions,
              [id]: { status: "dismissed", reason },
            },
          },
    );
    toast.show(
      "Sugerencia descartada en el ejemplo. Tu decisión queda registrada.",
    );
  }

  function removeVisit(id: string) {
    if (mode !== "demo") return;
    setState((current) => {
      const visit = current.visits.find((v) => v.id === id);
      if (!visit || visit.source === "existing") return current;
      const decisions = { ...current.decisions };
      if (visit.recommendationId) delete decisions[visit.recommendationId];
      return {
        ...current,
        decisions,
        visits: current.visits.filter((v) => v.id !== id),
      };
    });
    toast.show("La visita de ejemplo se retiró del calendario.");
  }

  function review(id: string) {
    if (mode === "live") {
      setLiveState((current) => ({
        ...current,
        reviewed: [...new Set([...current.reviewed, id])],
      }));
      toast.show(
        "Observación revisada en esta sesión. El visitador debe confirmar su reporte.",
      );
      return;
    }
    setState((current) => ({
      ...current,
      reviewed: [...new Set([...current.reviewed, id])],
    }));
    toast.show(
      "Observación revisada en el ejemplo. Sigue pendiente de confirmar por el visitador.",
    );
  }

  function reset() {
    setState(initialDemoState());
    const snapshot = createDemoSnapshot();
    setDemoSnapshot(snapshot);
    sessionStorage.removeItem(PILOT_DEMO_STORAGE_KEY);
    setScope("all");
    toast.show("Datos de ejemplo restablecidos.");
  }

  return (
    <Context.Provider
      value={{
        basePath,
        mode,
        setMode,
        loading,
        loadError,
        refresh: () => {
          if (mode === 'demo') {
            setDemoSnapshot(readPilotDemo());
            toast.show('Datos de ejemplo actualizados.');
          } else {
            manualRefresh.current = true;
            setRevision((v) => v + 1);
            toast.show('Consultando los reportes del equipo.');
          }
        },
        today,
        representatives,
        analysis,
        demoSnapshot,
        updateDemo: (snapshot) => {
          setDemoSnapshot(snapshot);
          try {
            sessionStorage.setItem(
              PILOT_DEMO_STORAGE_KEY,
              JSON.stringify(snapshot),
            );
          } catch {
            /* Sigue en memoria. */
          }
        },
        scope,
        setScope,
        doctors,
        recommendations,
        visits,
        state: mode === "live" ? liveState : state,
        addVisit,
        accept,
        dismiss,
        removeVisit,
        review,
        reset,
        path: (segment = "") => `${basePath}${segment ? `/${segment}` : ""}`,
      }}
    >
      {children}
    </Context.Provider>
  );
}
