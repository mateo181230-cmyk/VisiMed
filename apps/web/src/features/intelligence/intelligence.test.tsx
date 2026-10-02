import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../../app/App";
import { db } from "../../db/db";
import { DOCTORS, INITIAL_VISITS, RECOMMENDATIONS } from "./demoData";
import { DEMO_STORAGE_KEY, readDemoState, schedulingError } from "./model";
import type { CalendarVisit } from "./types";
import { intelligenceApi } from '../../api/client';
import { createDemoSnapshot } from './pilotDemo';
import { REPRESENTATIVES } from './demoData';

const session = vi.hoisted(() => ({
  status: "anon" as "anon" | "authed",
  user: null as null | {
    id: string;
    role: string;
    full_name: string;
    phone: string;
    timezone: string;
  },
}));
const locationGate = vi.hoisted(() => vi.fn());
const signOutMock = vi.hoisted(() => vi.fn());
vi.mock("../auth/AuthProvider", () => ({
  AuthProvider: ({ children }: { children: ReactNode }) => children,
  useAuth: () => ({
    ...session,
    needsReauth: false,
    signIn: vi.fn(),
    signUp: vi.fn(),
    signOut: signOutMock,
  }),
}));
vi.mock("../../sync/SyncProvider", () => ({
  SyncProvider: ({ children }: { children: ReactNode }) => children,
  useOutboxCounts: () => ({ pending: 0, rejected: 0, expired: 0 }),
  useOnline: () => true,
  useEngineState: () => ({ online: true, busy: false, lastSuccessAt: null }),
}));
vi.mock("../geo/LocationGate", () => ({
  RequireLocation: ({ children }: { children: ReactNode }) => {
    locationGate();
    return children;
  },
}));
vi.mock("../../pwa", () => ({
  usePwaUpdate: () => ({ needRefresh: false, update: vi.fn() }),
  useInstallPrompt: () => ({ canInstall: false, install: vi.fn() }),
}));

function renderApp(path = "/inteligencia/demo") {
  window.history.replaceState({}, "", path);
  return { user: userEvent.setup(), ...render(<App />) };
}
function cardFor(name: string) {
  return screen.getByRole("heading", { name }).closest("article")!;
}
async function openOptions(user: ReturnType<typeof userEvent.setup>) {
  await user.click(
    screen.getByRole("link", { name: "Más opciones del módulo" }),
  );
  await screen.findByRole("heading", { name: "Más contexto" });
  await user.click(
    screen.getByRole("button", { name: "Opciones de la demostración" }),
  );
}
async function programNext(user: ReturnType<typeof userEvent.setup>) {
  await user.click(screen.getByRole("button", { name: "Programar visita" }));
  await user.click(
    within(screen.getByRole("dialog", { name: "Programar visita" })).getByRole(
      "button",
      { name: "Programar visita" },
    ),
  );
}
beforeEach(() => {
  signOutMock.mockReset().mockImplementation(async () => { session.status = 'anon'; session.user = null });
  session.status = "anon";
  session.user = null;
  sessionStorage.removeItem(DEMO_STORAGE_KEY);
  locationGate.mockClear();
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
});
afterEach(() => vi.restoreAllMocks());

describe('Botones del dashboard administrativo', () => {
  function adminSession() {
    session.status = 'authed';
    session.user = { id: 'admin', role: 'admin', full_name: 'Administrador', phone: '+573000000030', timezone: 'America/Bogota' };
  }
  it('cambia los datos, filtra, actualiza y conserva el ejemplo al volver el foco', async () => {
    adminSession();
    const snapshot = createDemoSnapshot();
    snapshot.representatives = [{ ...snapshot.representatives[0]!, id: 'real-rep' }];
    const api = vi.spyOn(intelligenceApi, 'snapshot').mockResolvedValue({ ok: true, data: snapshot });
    const { user } = renderApp('/inteligencia/resumen');
    await screen.findByRole('heading', { name: /Dashboard del equipo/ });
    await waitFor(() => expect(screen.queryByText('Consultando visitas y reportes…')).not.toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: 'Ejemplo para presentar' }));
    await user.selectOptions(screen.getByLabelText('Visitador del dashboard'), REPRESENTATIVES[0]!.id);
    expect(screen.getByLabelText('Visitador del dashboard')).toHaveValue(REPRESENTATIVES[0]!.id);
    await user.click(screen.getByRole('button', { name: 'Actualizar reportes' }));
    expect(await screen.findByText('Datos de ejemplo actualizados.')).toBeInTheDocument();
    fireEvent(window, new Event('focus'));
    await waitFor(() => expect(api).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.queryByText('Consultando visitas y reportes…')).not.toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'Ejemplo para presentar' })).toHaveAttribute('aria-pressed', 'true');
    await user.click(screen.getByRole('button', { name: 'Datos reales' }));
    await waitFor(() => expect(screen.getByLabelText('Visitador del dashboard')).toHaveValue('all'));
  });
  it('abre la cuenta sin GPS y permite cancelar o confirmar el cierre de sesión', async () => {
    adminSession();
    const { user } = renderApp('/inteligencia/resumen');
    await user.click(await screen.findByRole('link', { name: 'Mi cuenta' }));
    await screen.findByRole('heading', { name: /Mi cuenta/ });
    expect(locationGate).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Cerrar sesión' }));
    await user.click(screen.getByRole('button', { name: 'Cancelar' }));
    expect(signOutMock).not.toHaveBeenCalled();
    await user.click(screen.getByRole('button', { name: 'Cerrar sesión' }));
    await user.click(screen.getByRole('button', { name: 'Confirmar cierre de sesión' }));
    await screen.findByRole('button', { name: 'Entrar' });
    expect(signOutMock).toHaveBeenCalledTimes(1);
  });
});

describe("Acceso y navegación móvil", () => {
  it("el ejemplo abre sin login y el módulo real conserva la autenticación", async () => {
    const app = renderApp();
    expect(
      await screen.findByRole("heading", { name: "Recomendaciones" }),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText("Datos simulados para el piloto"),
    ).toBeInTheDocument();
    app.unmount();
    renderApp("/inteligencia");
    expect(
      await screen.findByRole("button", { name: "Entrar" }),
    ).toBeInTheDocument();
  });
  it.each(["admin", "manager"])(
    "la cuenta %s llega al módulo sin pedir GPS",
    async (role) => {
      session.status = "authed";
      session.user = {
        id: "manager",
        role,
        full_name: "Cuenta de prueba",
        phone: "+57000",
        timezone: "America/Bogota",
      };
      renderApp(role === "admin" ? "/admin" : "/");
      expect(
        await screen.findByRole("heading", {
          name: role === "admin" ? /Dashboard del equipo/ : "Aún no hay recomendaciones",
        }),
      ).toBeInTheDocument();
      expect(window.location.pathname).toBe(role === "admin" ? "/inteligencia/resumen" : "/inteligencia");
      if (role === "admin") {
        expect(screen.getByRole("navigation", { name: "Panel de administrador" })).toBeInTheDocument();
        expect(screen.getByRole("link", { name: "Abrir Training Builder" })).toHaveAttribute("href", "/admin/training");
      }
      expect(locationGate).not.toHaveBeenCalled();
      expect(screen.queryByText("Dra. Elena Rojas")).not.toBeInTheDocument();
    },
  );
  it("el visitador accede desde una barra de exactamente cuatro destinos y conserva el historial en su cuenta", async () => {
    session.status = "authed";
    session.user = {
      id: "rep",
      role: "rep",
      full_name: "Visitador de prueba",
      phone: "+57000",
      timezone: "America/Bogota",
    };
    const { user } = renderApp("/agenda");
    await screen.findByRole("heading", { name: "Agenda" });
    const nav = screen.getByRole("navigation", { name: "Principal" });
    expect(
      within(nav)
        .getAllByRole("link")
        .map((link) => link.textContent),
    ).toEqual(["Hoy", "Agenda", "Recomendaciones", "Entrenar"]);
    await user.click(
      within(nav).getByRole("link", { name: "Recomendaciones" }),
    );
    expect(
      await screen.findByRole("heading", {
        name: "Aún no hay recomendaciones",
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Mi cuenta" })).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: "Mi cuenta" }));
    expect(
      await screen.findByRole("link", { name: "Historial de visitas" }),
    ).toHaveAttribute("href", "/historial");
  });
  it("no inventa datos en el estado vacío y permite explorar el ejemplo", async () => {
    const { user } = renderApp();
    await screen.findByRole("heading", { name: "Recomendaciones" });
    await openOptions(user);
    await user.selectOptions(
      screen.getByLabelText("Datos de la vista"),
      "empty",
    );
    await user.click(
      screen.getByRole("link", { name: "Volver a recomendaciones" }),
    );
    expect(
      await screen.findByRole("heading", {
        name: "Aún no hay recomendaciones",
      }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Dra. Elena Rojas")).not.toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: /Explorar con datos de ejemplo/ }),
    );
    expect(
      screen.getByRole("heading", { name: "Dra. Elena Rojas" }),
    ).toBeInTheDocument();
  });
});

describe("Siguiente acción y detalle bajo demanda", () => {
  it("muestra una sola tarjeta accionable y una lista breve, sin análisis ni filtros abiertos", async () => {
    renderApp();
    await screen.findByRole("heading", { name: "Dra. Elena Rojas" });
    expect(screen.getAllByRole("article")).toHaveLength(1);
    expect(
      screen.getAllByRole("button", { name: "Programar visita" }),
    ).toHaveLength(1);
    expect(screen.getAllByRole("link", { name: "Ver detalles" })).toHaveLength(
      1,
    );
    expect(
      screen.getByRole("heading", { name: "Otras sugerencias" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("La entrega de material sigue pendiente."),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("Médicos en el panel")).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText("Filtrar por visitador"),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });
  it("los detalles muestran la acción y solo abren un módulo de contexto a la vez", async () => {
    const { user } = renderApp();
    await screen.findByRole("heading", { name: "Dra. Elena Rojas" });
    await user.click(screen.getByRole("link", { name: "Ver detalles" }));
    await screen.findByRole("button", { name: "Por qué esta visita" });
    expect(
      screen.getByText(RECOMMENDATIONS[0]!.description),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(RECOMMENDATIONS[0]!.reasons[0]!.text),
    ).not.toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Por qué esta visita" }),
    );
    expect(
      screen.getByText(RECOMMENDATIONS[0]!.reasons[0]!.text),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Última visita e historial" }),
    );
    expect(
      screen.getByText(/Última visita:.*Hace 13 días/),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(RECOMMENDATIONS[0]!.reasons[0]!.text),
    ).not.toBeInTheDocument();
    expect(screen.getAllByRole("button", { expanded: true })).toHaveLength(1);
    await user.click(
      screen.getByRole("button", { name: "Territorio y disponibilidad" }),
    );
    expect(screen.getByText("Close-Up")).toBeInTheDocument();
    expect(screen.getByText("Sin datos conectados.")).toBeInTheDocument();
    expect(screen.queryByText(/Última visita:/)).not.toBeInTheDocument();
  });
});

describe("Directorio y evidencia por línea", () => {
  it("encuentra nombres sin tildes y aplica los filtros a la misma línea", async () => {
    const { user } = renderApp("/inteligencia/demo/medicos");
    await screen.findByRole("heading", { name: "Perfiles médicos" });
    expect(
      screen.queryByLabelText("Filtrar por línea"),
    ).not.toBeInTheDocument();
    await user.type(
      screen.getByRole("searchbox", { name: "Buscar médicos" }),
      "mejia",
    );
    expect(
      screen.getByRole("link", { name: "Abrir perfil de Dr. Andrés Mejía" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /Dra. Elena Rojas/ }),
    ).not.toBeInTheDocument();
    await user.clear(screen.getByRole("searchbox", { name: "Buscar médicos" }));
    await user.click(screen.getByRole("button", { name: "Filtrar" }));
    await user.selectOptions(
      screen.getByLabelText("Filtrar por línea"),
      "RESPI",
    );
    await user.selectOptions(
      screen.getByLabelText("Filtrar por estado"),
      "followup",
    );
    expect(
      screen.getByRole("link", { name: "Abrir perfil de Dr. Andrés Mejía" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /Dra. Elena Rojas/ }),
    ).not.toBeInTheDocument();
  });
  it("una línea sin contexto queda vacía, conserva la línea al planear y oculta los reportes", async () => {
    const { user } = renderApp(
      "/inteligencia/demo/medicos/elena-rojas?linea=OSTRU",
    );
    expect(
      await screen.findByRole("heading", {
        name: "Aún no hay contexto de Ostru",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/Pidió la ficha técnica/),
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Planear visita" }));
    const dialog = screen.getByRole("dialog", { name: "Planear una visita" });
    expect(within(dialog).getByLabelText("Línea")).toHaveValue("OSTRU");
    await user.click(within(dialog).getByRole("button", { name: "Cancelar" }));
    await user.click(screen.getByRole("button", { name: "Gastru" }));
    expect(
      screen.queryByRole("button", { name: "Ver reporte" }),
    ).not.toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Observaciones y evidencia" }),
    );
    expect(screen.getAllByRole("button", { name: "Ver reporte" })).toHaveLength(
      4,
    );
  });
  it("revisar una observación no la confirma ni crea una recomendación", async () => {
    const { user } = renderApp("/inteligencia/demo/medicos/felipe-salazar");
    await screen.findByRole("heading", { name: "Dr. Felipe Salazar" });
    await user.click(
      screen.getByRole("button", { name: "Observaciones y evidencia" }),
    );
    await user.click(screen.getByRole("button", { name: "Ver reporte" }));
    const dialog = screen.getByRole("dialog", {
      name: "Reporte que origina la observación",
    });
    await user.click(
      within(dialog).getByRole("button", { name: "Marcar como revisada" }),
    );
    await user.click(within(dialog).getByRole("button", { name: "Cerrar" }));
    expect(
      screen.getByText("Revisada · falta confirmación"),
    ).toBeInTheDocument();
    expect(
      DOCTORS.find((d) => d.id === "felipe-salazar")!.observations[0]!
        .confirmed,
    ).toBe(false);
    expect(RECOMMENDATIONS.some((r) => r.doctorId === "felipe-salazar")).toBe(
      false,
    );
  });
});

describe("De la recomendación al calendario", () => {
  it("programa una sola visita, abre su día, persiste y nunca escribe en la agenda real", async () => {
    const counts = [
      await db.doctors.count(),
      await db.visits.count(),
      await db.outbox.count(),
    ];
    const fetch = vi.spyOn(globalThis, "fetch");
    const app = renderApp();
    await screen.findByRole("heading", { name: "Dra. Elena Rojas" });
    await programNext(app.user);
    expect(
      screen.getByRole("heading", { name: "Dr. Andrés Mejía" }),
    ).toBeInTheDocument();
    await app.user.click(screen.getByRole("link", { name: "Ver agenda" }));
    expect(
      await screen.findByRole("button", {
        name: /Dra. Elena Rojas.*Desde una sugerencia/,
      }),
    ).toBeInTheDocument();
    expect(window.location.search).toBe("?fecha=2026-10-01");
    app.unmount();
    const saved = renderApp("/inteligencia/demo/recomendaciones/rec-elena");
    expect(
      await screen.findByRole("link", { name: "Ver visita programada" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Programar visita" }),
    ).not.toBeInTheDocument();
    expect(
      readDemoState().visits.filter((v) => v.recommendationId === "rec-elena"),
    ).toHaveLength(1);
    expect([
      await db.doctors.count(),
      await db.visits.count(),
      await db.outbox.count(),
    ]).toEqual(counts);
    expect(fetch).not.toHaveBeenCalled();
    saved.unmount();
  });
  it("explica un cruce de horario y permite ajustar solo la hora para programar", async () => {
    const conflict: CalendarVisit = {
      id: "conflict",
      doctorId: "valentina-castro",
      line: "GASTRU",
      day: "2026-10-01",
      time: "09:15",
      duration: 30,
      source: "manual",
    };
    sessionStorage.setItem(
      DEMO_STORAGE_KEY,
      JSON.stringify({
        visits: [...INITIAL_VISITS, conflict],
        decisions: {},
        reviewed: [],
      }),
    );
    const { user } = renderApp();
    await screen.findByRole("heading", { name: "Dra. Elena Rojas" });
    await user.click(screen.getByRole("button", { name: "Programar visita" }));
    const dialog = screen.getByRole("dialog", { name: "Programar visita" });
    await user.click(
      within(dialog).getByRole("button", { name: "Programar visita" }),
    );
    expect(within(dialog).getByRole("alert")).toHaveTextContent(
      /ya tiene una visita/,
    );
    fireEvent.change(within(dialog).getByLabelText("Hora"), {
      target: { value: "09:45" },
    });
    await user.click(
      within(dialog).getByRole("button", { name: "Programar visita" }),
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(
      readDemoState().visits.find((v) => v.recommendationId === "rec-elena")
        ?.time,
    ).toBe("09:45");
  });
  it("descartar desde detalles registra el motivo y promueve la siguiente sugerencia", async () => {
    const { user } = renderApp("/inteligencia/demo/recomendaciones/rec-elena");
    await screen.findByRole("button", { name: "No es el momento" });
    await user.click(screen.getByRole("button", { name: "No es el momento" }));
    const dialog = screen.getByRole("dialog", { name: "Descartar sugerencia" });
    await user.click(
      within(dialog).getByRole("button", { name: "El médico pidió otra cosa" }),
    );
    await user.click(within(dialog).getByRole("button", { name: "Descartar" }));
    expect(
      screen.getByText("Descartada · El médico pidió otra cosa"),
    ).toBeInTheDocument();
    await user.click(
      screen.getByRole("link", { name: "Volver a recomendaciones" }),
    );
    expect(
      await screen.findByRole("heading", { name: "Dr. Andrés Mejía" }),
    ).toBeInTheDocument();
    expect(readDemoState().visits).toHaveLength(INITIAL_VISITS.length);
  });
  it("detecta cruces por visitador, permite visitas simultáneas de otro y valida fechas", () => {
    const visit: CalendarVisit = {
      id: "new",
      doctorId: "elena-rojas",
      line: "GASTRU",
      day: "2026-10-01",
      time: "09:30",
      duration: 30,
      source: "manual",
    };
    const first = {
      ...visit,
      id: "old",
      doctorId: "valentina-castro",
      time: "09:15",
    };
    expect(schedulingError(visit, [first])).toMatch(/ya tiene una visita/);
    expect(
      schedulingError({ ...visit, doctorId: "andres-mejia" }, [first]),
    ).toBeNull();
    expect(schedulingError({ ...visit, time: "09:45" }, [first])).toBeNull();
    expect(schedulingError({ ...visit, day: "2026-09-31" }, [])).toMatch(
      /Revisa la fecha/,
    );
  });
  it("filtrar por visitador mantiene coherentes las sugerencias y el calendario", async () => {
    const { user } = renderApp();
    await screen.findByRole("heading", { name: "Recomendaciones" });
    await openOptions(user);
    await user.selectOptions(
      screen.getByLabelText("Filtrar por visitador"),
      "ana",
    );
    await user.click(
      screen.getByRole("link", { name: "Volver a recomendaciones" }),
    );
    expect(
      await screen.findByRole("heading", { name: "Dra. Elena Rojas" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /Dr. Andrés Mejía/ }),
    ).not.toBeInTheDocument();
    await user.click(
      within(screen.getByRole("navigation", { name: "Principal" })).getByRole(
        "link",
        { name: "Agenda" },
      ),
    );
    expect(
      await screen.findByText("0 visitas programadas"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Dr. Felipe Salazar/ }),
    ).not.toBeInTheDocument();
  });
});

describe("Evidencia y recuperación del ejemplo", () => {
  it("cada razón apunta a una observación confirmada del mismo médico y línea", () => {
    for (const r of RECOMMENDATIONS) {
      const doctor = DOCTORS.find((d) => d.id === r.doctorId)!;
      for (const reason of r.reasons) {
        const observation = doctor.observations.find(
          (o) => o.id === reason.observationId,
        )!;
        expect(observation).toBeDefined();
        expect(observation.line).toBe(r.line);
        expect(observation.confirmed).toBe(true);
        expect(
          doctor.visits.some(
            (v) => v.id === observation.visitId && v.confirmed,
          ),
        ).toBe(true);
      }
    }
  });
  it("el almacenamiento dañado vuelve al ejemplo inicial", () => {
    sessionStorage.setItem(DEMO_STORAGE_KEY, "{bad json");
    expect(readDemoState().visits).toEqual(INITIAL_VISITS);
    sessionStorage.setItem(
      DEMO_STORAGE_KEY,
      JSON.stringify({
        visits: [...INITIAL_VISITS, { id: "broken" }],
        reviewed: [],
        decisions: {},
      }),
    );
    expect(readDemoState().visits).toEqual(INITIAL_VISITS);
  });
  it("restablecer elimina decisiones y mantiene explícito que el modelo no está entrenado", async () => {
    const { user } = renderApp();
    await screen.findByRole("heading", { name: "Dra. Elena Rojas" });
    await programNext(user);
    await openOptions(user);
    await user.click(
      screen.getByRole("button", { name: "Restablecer ejemplo" }),
    );
    await user.click(
      screen.getByRole("link", { name: "Volver a recomendaciones" }),
    );
    await waitFor(() =>
      expect(
        within(cardFor("Dra. Elena Rojas")).getByRole("button", {
          name: "Programar visita",
        }),
      ).toBeInTheDocument(),
    );
    await user.click(
      screen.getByRole("link", { name: "Más opciones del módulo" }),
    );
    await user.click(
      await screen.findByRole("link", {
        name: /Acerca de las recomendaciones/,
      }),
    );
    expect(
      await screen.findByText("Machine learning · Aún sin entrenar"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Conteos ficticios/)).not.toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: "Qué información está disponible" }),
    );
    expect(screen.getByText(/Conteos ficticios/)).toBeInTheDocument();
  });
});
