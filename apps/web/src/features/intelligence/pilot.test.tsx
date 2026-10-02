import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ToastProvider } from "../../components/Toast";
import { intelligenceApi } from "../../api/client";
import { db } from "../../db/db";
import { IntelligenceProvider } from "./IntelligenceProvider";
import { PilotDemoScreen } from "./PilotDemoScreen";
import { analyzePilot } from "./pilot";
import {
  createDemoSnapshot,
  DEMO_DOCTOR_ID,
  DEMO_VISIT_ID,
  exampleReport,
  PILOT_DEMO_STORAGE_KEY,
} from "./pilotDemo";
import { DEMO_STORAGE_KEY } from "./model";
import { RecommendationsScreen } from "./RecommendationsScreen";

vi.mock("../auth/AuthProvider", () => ({
  useAuth: () => ({ user: { id: "ana", role: "rep" } }),
}));

function snapshotWithVisit(confirmed = false) {
  const s = createDemoSnapshot();
  const doctor = s.doctors.find((d) => d.id === DEMO_DOCTOR_ID)!;
  s.visits.push({
    id: DEMO_VISIT_ID,
    doctor_id: DEMO_DOCTOR_ID,
    representative_id: doctor.representative_id,
    primary_line_id: "GASTRU",
    discussed_line_ids: ["GASTRU"],
    scheduled_at: "2026-09-30T15:00:00Z",
    arrived_at: "2026-09-30T15:00:00Z",
    finished_at: "2026-09-30T15:08:00Z",
    status: confirmed ? "confirmed" : "ready",
    arrival_geo_state: "verificada",
    finish_geo_state: "verificada",
  });
  s.reports.push({
    ...exampleReport(),
    status: confirmed ? "confirmed" : "ready",
  });
  return s;
}

beforeEach(async () => {
  vi.restoreAllMocks();
  sessionStorage.removeItem(PILOT_DEMO_STORAGE_KEY);
  sessionStorage.removeItem(DEMO_STORAGE_KEY);
  await db.outbox.clear();
});

describe("Inteligencia alimentada por el reporte", () => {
  it("una visita pendiente suma actividad y su confirmación alimenta insights y próximo paso", () => {
    const base = analyzePilot(createDemoSnapshot());
    const pending = analyzePilot(snapshotWithVisit());
    expect(pending.metrics.completed).toBe(base.metrics.completed + 1);
    expect(pending.insights.competitors).toEqual(base.insights.competitors);
    expect(
      pending.recommendations.some((r) => r.id === `followup-${DEMO_VISIT_ID}`),
    ).toBe(false);
    const ready = analyzePilot(snapshotWithVisit(true));
    expect(ready.metrics.confirmed).toBe(base.metrics.confirmed + 1);
    const next = ready.recommendations.find(
      (r) => r.id === `followup-${DEMO_VISIT_ID}`,
    )!;
    expect(next.day).toBe("2026-10-07");
    expect(next.description).toMatch(/ficha técnica/);
    expect(next.reasons[0]?.observationId).toBe(`${DEMO_VISIT_ID}-next_action`);
    expect(
      ready.insights.competitors.some((s) => s.label === "pantoprazol"),
    ).toBe(true);
  });
  it("usa productos efectivamente conversados y no presume el producto de la agenda", () => {
    const s = snapshotWithVisit(true);
    s.reports.find(
      (r) => r.visit_id === DEMO_VISIT_ID,
    )!.fields.products_discussed!.value = "RESPI";
    s.visits.find((v) => v.id === DEMO_VISIT_ID)!.discussed_line_ids = [
      "RESPI",
    ];
    const result = analyzePilot(s);
    expect(
      result.insights.products.find((s) => s.label === "RESPI"),
    ).toBeDefined();
    expect(
      result.recommendations.find((r) => r.id === `followup-${DEMO_VISIT_ID}`)
        ?.title,
    ).toContain("RESPI");
    expect(
      result.recommendations.find((r) => r.id === `followup-${DEMO_VISIT_ID}`)
        ?.line,
    ).toBe("RESPI");
    expect(
      result.doctors
        .find((d) => d.id === DEMO_DOCTOR_ID)
        ?.visits.find((v) => v.id === DEMO_VISIT_ID)?.line,
    ).toBe("RESPI");
  });
  it("excluye baja confianza y no usa interés como puntuación de receptividad", () => {
    const s = snapshotWithVisit(true);
    const report = s.reports.find((r) => r.visit_id === DEMO_VISIT_ID)!;
    delete report.fields.receptiveness_score;
    report.fields.interest_level = {
      value: 5,
      confidence: "high",
      source: "call",
    };
    report.fields.competitor!.confidence = "low";
    const before = analyzePilot(createDemoSnapshot());
    const after = analyzePilot(s);
    expect(after.insights.receptive).toEqual(before.insights.receptive);
    expect(after.insights.competitors).toEqual(before.insights.competitors);
  });
  it("una negativa explícita no genera interés ni una acción de seguimiento ficticia", () => {
    const s = snapshotWithVisit(true);
    s.visits = s.visits.filter((v) => v.id === DEMO_VISIT_ID);
    s.reports = s.reports.filter((r) => r.visit_id === DEMO_VISIT_ID);
    const report = s.reports[0]!;
    report.fields.products_discussed!.value = "ESOMED, esomed";
    report.fields.doctor_interest!.value = "No mostró interés en nada";
    report.fields.commitment!.value = "No quedaron compromisos";
    report.fields.next_action!.value = "No se acordó próximo paso";
    const result = analyzePilot(s);
    expect(
      result.recommendations.some((r) =>
        r.id.startsWith(`followup-${DEMO_VISIT_ID}`),
      ),
    ).toBe(false);
    expect(result.insights.productInterest).toEqual([
      { label: "esomed", reports: 1, interested: 0 },
    ]);
    expect(result.insights.interests).toEqual([]);
  });
  it("detecta duración corta, ubicación incompleta, repetición y horarios atípicos", () => {
    const s = snapshotWithVisit();
    const visit = s.visits.find((v) => v.id === DEMO_VISIT_ID)!;
    visit.finished_at = "2026-09-30T15:02:00Z";
    visit.finish_geo_state = "sin_gps";
    s.reports.find((r) => r.visit_id === DEMO_VISIT_ID)!.complete = false;
    s.visits.push(
      { ...visit, id: "repeat-2" },
      { ...visit, id: "repeat-3", finished_at: "2026-09-30T14:59:00Z" },
    );
    const result = analyzePilot(s);
    expect(result.alerts.map((a) => a.kind)).toEqual(
      expect.arrayContaining([
        "short_visit",
        "incomplete",
        "location",
        "repetitive",
        "atypical",
      ]),
    );
    expect(result.metrics.averageMinutes).toBeGreaterThan(0);
  });
  it("agrupa objeciones de precio aunque los visitadores usen frases diferentes", () => {
    const s = snapshotWithVisit(true);
    s.visits = s.visits.filter((v) => v.id === DEMO_VISIT_ID);
    s.reports = s.reports.filter((r) => r.visit_id === DEMO_VISIT_ID);
    const report = s.reports[0]!;
    report.fields.objection!.value = "Preguntó por el precio";
    s.visits.push({ ...s.visits[0]!, id: "other-price-report" });
    s.reports.push({
      ...report,
      visit_id: "other-price-report",
      fields: {
        ...report.fields,
        objection: {
          value: "Le pareció costoso",
          confidence: "high",
          source: "call",
        },
      },
    });
    expect(analyzePilot(s).insights.objections).toEqual([
      { label: "Precio o cobertura", count: 2 },
    ]);
  });
  it("filtra por visitador y excluye fechas futuras de la actividad", () => {
    const s = snapshotWithVisit(true);
    s.visits.push({
      ...s.visits.find((v) => v.id === DEMO_VISIT_ID)!,
      id: "future",
      finished_at: "2026-10-01T15:05:00Z",
      scheduled_at: "2026-10-01T15:00:00Z",
    });
    const result = analyzePilot(s, "ana");
    expect(result.metrics.byRep.map((r) => r.id)).toEqual(["ana"]);
    expect(result.metrics.daily.some((d) => d.day === "2026-10-01")).toBe(
      false,
    );
    expect(
      result.doctors
        .flatMap((d) => d.visits)
        .every((v) => v.representativeId === "ana"),
    ).toBe(true);
  });
});

describe("Recorrido demostrable", () => {
  it("el nuevo seguimiento confirmado reemplaza la sugerencia anterior del mismo médico y línea", () => {
    sessionStorage.setItem(
      PILOT_DEMO_STORAGE_KEY,
      JSON.stringify(snapshotWithVisit(true)),
    );
    render(
      <MemoryRouter>
        <ToastProvider>
          <IntelligenceProvider preview>
            <RecommendationsScreen />
          </IntelligenceProvider>
        </ToastProvider>
      </MemoryRouter>,
    );
    expect(
      screen.getByRole("heading", { name: "Dra. Elena Rojas" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Seguimiento reportado para 2026-10-07"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /Dra. Elena Rojas/ }),
    ).not.toBeInTheDocument();
  });
  it("llegar, terminar, conversar, corregir y confirmar guarda un único reporte sin enviar eventos reales", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <ToastProvider>
          <IntelligenceProvider preview>
            <PilotDemoScreen />
          </IntelligenceProvider>
        </ToastProvider>
      </MemoryRouter>,
    );
    await user.click(
      screen.getByRole("button", { name: "Llegué · 10:00 a. m." }),
    );
    await user.click(
      screen.getByRole("button", { name: "Terminé · 10:08 a. m." }),
    );
    await user.click(
      screen.getByRole("button", { name: "Contestar llamada simulada" }),
    );
    for (let i = 0; i < 10; i++)
      await user.click(
        screen.getByRole("button", {
          name: i % 2 ? "Escuchar a UNO" : "Responder con el relato de ejemplo",
        }),
      );
    await user.click(
      screen.getByRole("button", { name: "Corregir la fecha de seguimiento" }),
    );
    fireEvent.change(screen.getByLabelText("Nueva fecha de seguimiento"), {
      target: { value: "2026-10-14" },
    });
    await user.click(
      screen.getByRole("button", { name: "Sí, correcto · guardar reporte" }),
    );
    expect(
      screen
        .getAllByRole("status")
        .some((s) => s.textContent?.includes("Reporte confirmado y guardado")),
    ).toBe(true);
    const saved = JSON.parse(sessionStorage.getItem(PILOT_DEMO_STORAGE_KEY)!);
    expect(
      saved.reports.filter(
        (r: { visit_id: string }) => r.visit_id === DEMO_VISIT_ID,
      ),
    ).toHaveLength(1);
    expect(
      saved.reports.find(
        (r: { visit_id: string }) => r.visit_id === DEMO_VISIT_ID,
      ).fields.next_action_due.value,
    ).toBe("2026-10-14");
    expect(await db.outbox.count()).toBe(0);
  });
  it("las recomendaciones conectadas programan en la agenda real mediante la cola", async () => {
    const s = snapshotWithVisit(true);
    s.doctors = s.doctors.filter((d) => d.id === DEMO_DOCTOR_ID);
    s.visits = s.visits.filter((v) => v.id === DEMO_VISIT_ID);
    s.reports = s.reports.filter((r) => r.visit_id === DEMO_VISIT_ID);
    vi.spyOn(intelligenceApi, "snapshot").mockResolvedValue({
      ok: true,
      data: s,
    });
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <ToastProvider>
          <IntelligenceProvider>
            <RecommendationsScreen />
          </IntelligenceProvider>
        </ToastProvider>
      </MemoryRouter>,
    );
    await user.click(
      await screen.findByRole("button", { name: "Programar visita" }),
    );
    await user.click(
      within(
        screen.getByRole("dialog", { name: "Programar visita" }),
      ).getByRole("button", {
        name: "Programar visita",
      }),
    );
    expect(await screen.findByText("Visita programada")).toBeInTheDocument();
    const events = await db.outbox.toArray();
    expect(events).toHaveLength(1);
    expect(events[0]!.type).toBe("visit_scheduled");
    expect(events[0]!.payload.doctor_id).toBe(DEMO_DOCTOR_ID);
    expect(events[0]!.payload.scheduled_at).toBe("2026-10-07T14:00:00.000Z");
  });
});
