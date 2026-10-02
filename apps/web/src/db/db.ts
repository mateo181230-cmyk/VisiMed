/**
 * Base de datos local (IndexedDB con Dexie). Es la fuente de verdad de lo que ve la pantalla
 * (doc 01 §10.1): el estado del servidor (foto) más los eventos aún no confirmados (cola).
 *
 * Las tablas de entidades guardan **solo** la foto del servidor. Lo que el visitador hizo y aún no
 * se confirma vive en ``outbox`` y se aplica encima al leer (ver ``sync/overlay.ts``). Así un
 * evento rechazado desaparece de la pantalla sin necesidad de deshacer nada.
 */
import Dexie, { type Table } from 'dexie'
import type { GeoEstado } from '../features/geo/tipos'

export interface LineRow {
  id: string
  code: string
  name: string
  active: boolean
}

export interface ProductRow {
  id: string
  line_id: string
  name: string
  active: boolean
}

export interface InstitutionRow {
  id: string
  name: string
  address: string | null
  city: string | null
  lat: number | null
  lng: number | null
  radius_m: number
}

export interface DoctorRow {
  id: string
  full_name: string
  specialty: string | null
  institution_id: string | null
  review_state: string
  default_line_id: string | null
}

export type VisitStatus =
  | 'scheduled'
  | 'in_progress'
  | 'finished'
  | 'not_done'
  | 'in_call'
  | 'processing'
  | 'ready'
  | 'error'
  | 'confirmed'
  | 'no_interview'

/** Cómo quedó la ubicación de un toque (Llegué o Terminé) frente al lugar de la visita. */
export interface GeoResult {
  state: GeoEstado
  distance_m: number | null
  precision_m: number | null
}

/** La llamada de resumen de una visita mientras sigue viva (por marcar o en curso). */
export interface CallInfo {
  status: 'queued' | 'dialing'
  attempt: number
  next_at: string | null
  reason: string | null
}

export interface VisitRow {
  title?: string | null
  id: string
  doctor_id: string
  institution_id: string | null
  primary_line_id: string
  line_ids: string[]
  /** ISO 8601 en UTC */
  scheduled_at: string
  status: VisitStatus
  planned_by: string
  not_done_reason: string | null
  updated_at: string
  /** Hora del toque «Llegué» / «Terminé» (ISO, UTC). */
  arrived_at?: string | null
  finished_at?: string | null
  report_notified_at?: string | null
  report_due_at?: string | null
  report_invalid_at?: string | null
  report_mode?: string | null
  arrival_geo?: GeoResult | null
  finish_geo?: GeoResult | null
  call?: CallInfo | null
}

export type ReportValue = string | number | boolean | null

/** Un dato de la ficha: lo que dijo el visitador en la llamada (`call`) o lo que corrigió él (`rep_edit`). */
export interface ReportField {
  value: ReportValue
  confidence: 'high' | 'medium' | 'low' | string
  source: 'call' | 'rep_edit' | string
}

/** La ficha (resumen) de una visita. */
export interface ReportRow {
  visit_id: string
  status: 'ready' | 'confirmed'
  complete: boolean
  fields: Record<string, ReportField>
  confirmed_at: string | null
  updated_at: string
}

/** `capturing`: el toque ya quedó registrado y está esperando su ubicación; el motor aún no lo envía. */
export type OutboxStatus = 'capturing' | 'pending' | 'sending' | 'confirmed' | 'rejected' | 'expired'

export interface OutboxRow {
  seq?: number
  event_id: string
  type: string
  visit_id: string | null
  /** Hora del toque en el teléfono (ISO, UTC) */
  device_ts: string
  payload: Record<string, unknown>
  status: OutboxStatus
  reason?: string | null
  attempts: number
  created_at: string
  confirmed_at?: string | null
}

export interface MetaRow {
  key: string
  value: unknown
}

export class UnoDB extends Dexie {
  lines!: Table<LineRow, string>
  products!: Table<ProductRow, string>
  institutions!: Table<InstitutionRow, string>
  doctors!: Table<DoctorRow, string>
  visits!: Table<VisitRow, string>
  reports!: Table<ReportRow, string>
  outbox!: Table<OutboxRow, number>
  meta!: Table<MetaRow, string>

  constructor(name = 'uno-visitas') {
    super(name)
    // Cada cambio de esquema es una versión nueva con su migración (doc 02 T2.3 ST2).
    this.version(1).stores({
      lines: 'id',
      products: 'id, line_id',
      institutions: 'id',
      doctors: 'id, full_name',
      visits: 'id, scheduled_at, status',
      outbox: '++seq, &event_id, status',
      meta: 'key',
    })
    // v2: fichas (resúmenes de la llamada). Las tablas anteriores no cambian. Al subir de versión se
    // olvida el cursor de bajada: si no, una app vieja que siguió sincronizando sin conocer las fichas
    // habría avanzado su cursor más allá de ellas y nunca las recibiría (bajada incremental).
    this.version(2)
      .stores({ reports: 'visit_id, status, updated_at' })
      .upgrade((tx) => tx.table('meta').delete('cursor'))
    this.version(3).stores({}).upgrade((tx) => tx.table('meta').delete('cursor'))
  }
}

export const db = new UnoDB()

export async function getMeta<T>(key: string, database: UnoDB = db): Promise<T | undefined> {
  return (await database.meta.get(key))?.value as T | undefined
}

export async function setMeta(key: string, value: unknown, database: UnoDB = db): Promise<void> {
  await database.meta.put({ key, value })
}

export async function delMeta(key: string, database: UnoDB = db): Promise<void> {
  await database.meta.delete(key)
}

/** Borra todos los datos locales (cierre de sesión, o cambio de usuario en el mismo teléfono). */
export async function wipeLocalData(database: UnoDB = db): Promise<void> {
  await database.transaction(
    'rw',
    [
      database.lines,
      database.products,
      database.institutions,
      database.doctors,
      database.visits,
      database.reports,
      database.outbox,
      database.meta,
    ],
    async () => {
      await Promise.all([
        database.lines.clear(),
        database.products.clear(),
        database.institutions.clear(),
        database.doctors.clear(),
        database.visits.clear(),
        database.reports.clear(),
        database.outbox.clear(),
        database.meta.clear(),
      ])
    },
  )
}
