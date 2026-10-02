import { Check, Pencil } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { Sheet } from "../../components/Sheet";
import { useToast } from "../../components/Toast";
import { Button, Chip, Notice } from "../../components/ui";
import { dateKey, formatLongDate, formatTime } from "../../lib/time";
import { reportConfirmed, reportFieldEdited } from "../../sync/events";
import type { EditableReportField } from "../../sync/events";
import { enqueue } from "../../sync/outbox";
import { formatDuration } from "../visit/format";
import { TouchSummary } from "../visit/VisitActions";
import {
  CALL_FAILURE_LABEL,
  FIELD_DEFS,
  type FieldDef,
  SUMMARY_DEF,
  displayValue,
  fieldValue,
  isDoubtful,
} from "./labels";
import type { HistoryItem } from "./useHistory";
import {
  reportDeadlineLabel,
  reportExpired,
  reportPending,
} from "./reportDeadline";
import { useNow } from "../../lib/useNow";

/** Qué decirle al visitador cuando la visita aún no tiene resumen. */
export function pendingMessage(
  item: HistoryItem,
  tz: string,
): { tone: "info" | "warn"; text: string } | null {
  const { visit } = item.vm;
  if (reportExpired(visit, item.report))
    return {
      tone: "warn",
      text: "Resumen inválido: vencieron los 30 minutos desde el aviso. La visita realizada se conserva.",
    };
  if (visit.report_mode === "written" || visit.report_mode === "deferred")
    return {
      tone: "warn",
      text: `Tienes el resumen pendiente por escrito. ${reportDeadlineLabel(visit, tz)}`,
    };
  const call = visit.call;
  switch (visit.status) {
    case "in_call":
      return {
        tone: "info",
        text: "Te estamos llamando. Contesta y cuéntanos cómo te fue.",
      };
    case "processing":
      return { tone: "info", text: "Estamos armando tu resumen." };
    case "finished": {
      if (call?.next_at) {
        const why = call.reason
          ? `${CALL_FAILURE_LABEL[call.reason] ?? "No pudimos hablar"}. `
          : "";
        return {
          tone: "warn",
          text: `${why}Te llamamos de nuevo a las ${formatTime(call.next_at, tz)}.`,
        };
      }
      return {
        tone: "info",
        text: "En un momento te llamamos para que cuentes cómo te fue.",
      };
    }
    case "no_interview":
      return {
        tone: "warn",
        text: "No pudimos hablar contigo y esta visita quedó sin resumen.",
      };
    case "error":
      return {
        tone: "warn",
        text: "No pudimos armar el resumen de esta visita.",
      };
    case "not_done":
      return { tone: "info", text: "Esta visita no se realizó." };
    default:
      return null;
  }
}

function ScaleEditor({
  value,
  onPick,
}: {
  value: number | null;
  onPick: (n: number) => void;
}) {
  const names = ["Muy bajo", "Bajo", "Medio", "Alto", "Muy alto"];
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-5 gap-2">
        {[1, 2, 3, 4, 5].map((n) => (
          <Chip
            key={n}
            selected={value === n}
            className="px-0 text-xl font-bold"
            onClick={() => onPick(n)}
          >
            {n}
          </Chip>
        ))}
      </div>
      <div className="flex justify-between px-1 text-xs text-muted">
        <span>{names[0]}</span>
        <span>{names[4]}</span>
      </div>
    </div>
  );
}

function TextEditor({
  def,
  initial,
  onSave,
  summary = false,
}: {
  def: Extract<FieldDef["editor"], { kind: "text" }>;
  initial: string;
  onSave: (value: string | null) => void;
  summary?: boolean;
}) {
  const [text, setText] = useState(initial);
  const guideId = useId();
  return (
    <div className="space-y-3">
      {summary && (
        <div id={guideId} className="space-y-2 rounded-control bg-brand-50 p-3.5 text-sm text-navy">
          <p className="font-semibold">Cuenta lo que ocurrió en la visita:</p>
          <ul className="list-disc space-y-1 pl-4">
            <li><strong>Producto o línea:</strong> qué presentaste.</li>
            <li><strong>Objetivo:</strong> qué buscabas lograr.</li>
            <li><strong>Reacción:</strong> qué dijo, preguntó o le interesó al médico.</li>
            <li><strong>Compromiso:</strong> qué acordaron y quién lo hará.</li>
            <li><strong>Próximo paso:</strong> qué sigue y la fecha, si la acordaron.</li>
          </ul>
          <p>Si no hubo un acuerdo, indícalo. Incluye solo lo que ocurrió.</p>
        </div>
      )}
      <textarea
        autoFocus
        value={text}
        maxLength={def.max}
        rows={def.multiline ? 5 : 3}
        onChange={(e) => setText(e.target.value)}
        aria-label={summary ? "Resumen de la visita" : "Nuevo valor"}
        aria-describedby={summary ? guideId : undefined}
        placeholder={summary ? "Escribe aquí el resumen de tu visita…" : undefined}
        className="w-full rounded-control border border-line bg-white p-3.5 text-base focus:border-brand"
      />
      <p className="text-right text-xs text-muted">
        {text.length}/{def.max}
      </p>
      <div className="flex gap-2">
        {initial && (
          <Button
            variant="outline"
            className="flex-1"
            onClick={() => onSave(null)}
          >
            Borrar
          </Button>
        )}
        <Button
          className="flex-1"
          disabled={text.trim() === initial.trim()}
          onClick={() => onSave(text)}
        >
          Guardar
        </Button>
      </div>
    </div>
  );
}

interface Props {
  item: HistoryItem | null;
  tz: string;
  onClose: () => void;
}

/** La ficha de una visita: lo que contó el visitador. Se confirma con un toque y cada dato se puede corregir. */
export function ReportSheet({ item, tz, onClose }: Props) {
  const toast = useToast();
  const now = useNow(10_000);
  const [editing, setEditing] = useState<FieldDef | null>(null);
  const visitId = item?.vm.visit.id;

  useEffect(() => {
    setEditing(null);
  }, [visitId]);

  if (!item) return null;
  const { vm, report } = item;
  const { visit, doctor, institution } = vm;
  const finishedAt = visit.finished_at ?? visit.scheduled_at;
  const spent =
    visit.arrived_at && visit.finished_at
      ? formatDuration(
          Date.parse(visit.finished_at) - Date.parse(visit.arrived_at),
        )
      : null;

  async function save(
    field: EditableReportField,
    value: string | number | boolean | null,
  ): Promise<void> {
    await enqueue(reportFieldEdited(visit.id, field, value));
    // Que los datos no se contradigan: un pedido no tiene «motivo de no pedido».
    if (field === "order_taken") {
      if (value === true)
        await enqueue(
          reportFieldEdited(visit.id, "no_order_reason", "not_applicable"),
        );
      else if (report?.fields.no_order_reason?.value === "not_applicable") {
        await enqueue(reportFieldEdited(visit.id, "no_order_reason", null));
      }
    }
    toast.show("Corregido");
    setEditing(null);
  }

  async function confirm(): Promise<void> {
    await enqueue(reportConfirmed(visit.id));
    toast.show("Resumen confirmado");
    onClose();
  }

  const expired = reportExpired(visit, report, now);
  const message = report && !expired ? null : pendingMessage(item, tz);
  const rows = report
    ? FIELD_DEFS.filter((d) => !d.when || d.when(report))
    : [];

  const editorFor = (def: FieldDef) => {
    const current = report ? fieldValue(report, def.key) : null;
    const e = def.editor;
    if (e.kind === "date") {
      return (
        <div className="space-y-3">
          <input
            type="date"
            aria-label="Fecha de seguimiento"
            className="w-full rounded-control border border-line p-3"
            value={
              typeof current === "string"
                ? current
                : typeof report?.fields.next_action_due?.value === "string"
                  ? report.fields.next_action_due.value
                  : ""
            }
            onChange={(event) => void save(def.key, event.target.value || null)}
          />
          <Button
            variant="outline"
            block
            onClick={() => void save(def.key, null)}
          >
            Sin fecha acordada
          </Button>
        </div>
      );
    }
    if (e.kind === "scale") {
      return (
        <ScaleEditor
          value={typeof current === "number" ? current : null}
          onPick={(n) => void save(def.key, n)}
        />
      );
    }
    if (e.kind === "bool") {
      return (
        <div className="grid grid-cols-2 gap-2">
          <Chip
            selected={current === true}
            onClick={() => void save(def.key, true)}
          >
            Sí
          </Chip>
          <Chip
            selected={current === false}
            onClick={() => void save(def.key, false)}
          >
            No
          </Chip>
        </div>
      );
    }
    if (e.kind === "choice") {
      return (
        <div className="flex flex-col gap-2">
          {e.options.map(([value, label]) => (
            <Chip
              key={value}
              selected={current === value}
              className="text-left"
              onClick={() => void save(def.key, value)}
            >
              {label}
            </Chip>
          ))}
        </div>
      );
    }
    return (
      <TextEditor
        def={e}
        summary={def.key === "summary"}
        initial={typeof current === "string" ? current : ""}
        onSave={(value) => void save(def.key, value)}
      />
    );
  };

  const footer =
    editing === null && report?.status === "ready" ? (
      <Button
        size="lg"
        block
        disabled={expired}
        icon={<Check size={22} />}
        onClick={() => void confirm()}
      >
        Confirmar
      </Button>
    ) : editing !== null ? (
      <Button variant="ghost" block onClick={() => setEditing(null)}>
        Volver
      </Button>
    ) : undefined;

  return (
    <Sheet
      open
      onClose={onClose}
      title={editing ? editing.label : (doctor?.full_name ?? "Visita")}
      footer={footer}
    >
      {editing ? (
        <div className="pt-1">{editorFor(editing)}</div>
      ) : (
        <div className="space-y-5 pt-1">
          <div>
            <p className="text-base text-muted">
              {formatLongDate(dateKey(finishedAt, tz))} ·{" "}
              {formatTime(finishedAt, tz)}
              {spent ? ` · ${spent}` : ""}
            </p>
            {institution && (
              <p className="text-base text-muted">{institution.name}</p>
            )}
            {institution?.address && (
              <p className="text-sm text-muted">{institution.address}</p>
            )}
            <p className="text-sm text-muted">
              Llegada:{" "}
              {visit.arrived_at
                ? formatTime(visit.arrived_at, tz)
                : "Sin registro"}
              {" · "}Salida:{" "}
              {visit.finished_at
                ? formatTime(visit.finished_at, tz)
                : "Sin registro"}
            </p>
          </div>

          {message && <Notice tone={message.tone}>{message.text}</Notice>}
          {!expired && reportPending(visit, report) && (
            <Notice tone="warn">
              Resumen pendiente. {reportDeadlineLabel(visit, tz)}
            </Notice>
          )}
          {(!report || !fieldValue(report, "summary")) &&
            reportPending(visit, report) && (
              <Button
                block
                variant="soft"
                icon={<Pencil size={18} />}
                onClick={() => setEditing(SUMMARY_DEF)}
              >
                {expired
                  ? "Guardar resumen fuera de plazo"
                  : "Escribir resumen"}
              </Button>
            )}
          {vm.unsent && (
            <Notice tone="info">
              Guardado en tu teléfono. Se enviará cuando haya conexión.
            </Notice>
          )}

          {report && (
            <>
              {!report.complete && (
                <Notice tone="warn">
                  Faltan datos esenciales del reporte. Puedes agregar lo
                  pendiente; no se inventaron respuestas.
                </Notice>
              )}
              {fieldValue(report, "summary") ? (
                <button
                  type="button"
                  onClick={() => setEditing(SUMMARY_DEF)}
                  className="w-full rounded-card bg-brand-50 p-4 text-left text-[16px] leading-relaxed text-navy active:bg-brand-100"
                >
                  {String(fieldValue(report, "summary"))}
                </button>
              ) : null}

              <ul className="divide-y divide-line overflow-hidden rounded-card border border-line">
                {rows.map((def) => {
                  const field = report.fields[def.key];
                  const text = displayValue(
                    def.key,
                    fieldValue(report, def.key) ??
                      (def.key === "next_action_date"
                        ? fieldValue(report, "next_action_due")
                        : null),
                  );
                  return (
                    <li key={def.key}>
                      <button
                        type="button"
                        onClick={() => setEditing(def)}
                        aria-label={`${def.label}: ${text ?? "sin dato"}. Corregir`}
                        className="flex min-h-14 w-full items-start gap-3 px-4 py-3 text-left active:bg-canvas"
                      >
                        <span className="w-[104px] shrink-0 pt-0.5 text-sm font-semibold text-muted">
                          {def.label}
                        </span>
                        <span className="min-w-0 flex-1">
                          <span
                            className={
                              text
                                ? "block text-[16px]"
                                : "block text-[16px] text-muted"
                            }
                          >
                            {text ?? "Sin dato · toca para agregar"}
                          </span>
                          {isDoubtful(field) && (
                            <span className="mt-1 inline-block rounded bg-warn-50 px-1.5 py-0.5 text-xs font-bold text-warn">
                              Revisar
                            </span>
                          )}
                          {field?.source === "rep_edit" && (
                            <span className="mt-1 ml-1 inline-block rounded bg-line/70 px-1.5 py-0.5 text-xs font-semibold text-muted">
                              Corregido por ti
                            </span>
                          )}
                        </span>
                        <Pencil
                          size={16}
                          className="mt-1 shrink-0 text-muted"
                          aria-hidden
                        />
                      </button>
                    </li>
                  );
                })}
              </ul>

              {report.status === "confirmed" ? (
                <Notice tone="ok">
                  Resumen confirmado. Si algo cambió, toca el dato para
                  corregirlo.
                </Notice>
              ) : (
                <p className="text-sm text-muted">
                  Revisa que esté bien y confirma. Corregir un dato es opcional.
                </p>
              )}
            </>
          )}

          <TouchSummary vm={vm} />
        </div>
      )}
    </Sheet>
  );
}
