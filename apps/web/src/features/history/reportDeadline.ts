import type { ReportRow, VisitRow } from "../../db/db";
import { formatTime } from "../../lib/time";

export function reportExpired(
  visit: VisitRow,
  report: ReportRow | null | undefined,
  now = new Date(),
): boolean {
  if (report?.status === "confirmed" && !visit.report_invalid_at) return false;
  return (
    !!visit.report_invalid_at ||
    (!!visit.report_due_at && now.getTime() >= Date.parse(visit.report_due_at))
  );
}

export function reportPending(
  visit: VisitRow,
  report: ReportRow | null | undefined,
): boolean {
  return (
    report?.status !== "confirmed" &&
    [
      "finished",
      "in_call",
      "processing",
      "ready",
      "no_interview",
      "error",
    ].includes(visit.status)
  );
}

export function reportDeadlineLabel(visit: VisitRow, tz: string): string {
  return visit.report_due_at
    ? `Completa y confirma tu resumen antes de las ${formatTime(visit.report_due_at, tz)}.`
    : "El plazo de 30 minutos empieza cuando te llamemos para solicitar el resumen.";
}
