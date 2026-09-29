/**
 * Motor de sincronización (doc 01 §10.3–§10.7; doc 02 T2.4).
 *
 * 1. **Sube** los eventos pendientes por lotes (≤ 100) en orden de ``device_ts``.
 * 2. **Baja** el estado incremental desde el cursor y lo guarda como foto del servidor.
 * 3. Si no hay red o el servidor falla: reintenta con retroceso exponencial (1-2-4-8 min, luego
 *    cada 8) hasta 24 h; después el evento queda «vencido» y se reintenta con un toque.
 *
 * Nada de esto bloquea la interfaz: la pantalla lee de la base local.
 */
import { UnoDB, db, getMeta, setMeta } from '../db/db'
import type { ApiResult, StateOut, SyncOut, WireEvent } from '../api/client'
import { newId } from '../lib/ids'
import { backoffDelayMs, isExpired } from './backoff'
import { onOutboxChanged, recoverCapturing } from './outbox'

export const APP_VERSION = '0.1.0'
const BATCH = 100
const POLL_MS = 30_000

export interface SyncPort {
  postSync(deviceId: string, events: WireEvent[], pending: number): Promise<ApiResult<SyncOut>>
  fetchState(cursor: number | null): Promise<ApiResult<StateOut>>
}

export type EngineState = 'idle' | 'syncing' | 'offline' | 'error' | 'auth'

export interface EngineOptions {
  now?: () => number
  random?: () => number
}

type Outcome = 'ok' | 'network' | 'server' | 'auth'

export class SyncEngine {
  private state: EngineState = 'idle'
  private running = false
  private current: Promise<void> | null = null
  private rerun = false
  private nextAttemptAt = 0
  private failures = 0
  private timer: ReturnType<typeof setTimeout> | null = null
  private listeners = new Set<() => void>()
  private teardown: Array<() => void> = []
  private readonly now: () => number
  private readonly random: () => number

  constructor(
    private readonly port: SyncPort,
    private readonly database: UnoDB = db,
    options: EngineOptions = {},
  ) {
    this.now = options.now ?? Date.now
    this.random = options.random ?? Math.random
  }

  // --- estado observable (useSyncExternalStore)
  subscribe = (fn: () => void): (() => void) => {
    this.listeners.add(fn)
    return () => this.listeners.delete(fn)
  }
  getState = (): EngineState => this.state
  private set(state: EngineState): void {
    if (this.state === state) return
    this.state = state
    for (const fn of this.listeners) fn()
  }

  // --- ciclo de vida
  async start(): Promise<void> {
    // Un envío que quedó a medias por un cierre de la app vuelve a la cola.
    await this.database.outbox.where('status').equals('sending').modify({ status: 'pending' })
    // Un toque de Llegué / Terminé que quedó esperando su ubicación cuando se cerró la app no se pierde.
    await recoverCapturing(this.database)
    const add = <K extends keyof WindowEventMap>(type: K, fn: () => void): void => {
      window.addEventListener(type, fn)
      this.teardown.push(() => window.removeEventListener(type, fn))
    }
    add('online', () => void this.run(true))
    const onVisible = (): void => {
      if (document.visibilityState === 'visible') void this.run(false)
    }
    document.addEventListener('visibilitychange', onVisible)
    this.teardown.push(() => document.removeEventListener('visibilitychange', onVisible))
    const poll = setInterval(() => void this.run(false), POLL_MS)
    this.teardown.push(() => clearInterval(poll))
    this.teardown.push(onOutboxChanged(() => void this.run(false)))
    void this.run(true)
  }

  stop(): void {
    for (const fn of this.teardown.splice(0)) fn()
    if (this.timer) clearTimeout(this.timer)
    this.timer = null
  }

  /**
   * ``force`` ignora la espera de reintento (volvió la red, o el usuario pidió reintentar).
   * Si ya hay un ciclo en curso devuelve ese mismo ciclo y programa otro al terminar.
   */
  run(force = false): Promise<void> {
    if (this.running) {
      this.rerun = true
      return this.current ?? Promise.resolve()
    }
    if (!force && this.now() < this.nextAttemptAt) return Promise.resolve()
    this.running = true
    this.current = this.execute()
    return this.current
  }

  private async execute(): Promise<void> {
    this.set('syncing')
    try {
      let outcome: Outcome
      try {
        outcome = await this.cycle()
      } catch (error) {
        // Un fallo inesperado (por ejemplo, la base local cerrada) nunca debe romper la app:
        // se trata como error transitorio y se reintenta.
        console.error('[sync] error inesperado', error)
        outcome = 'server'
      }
      this.finish(outcome)
    } finally {
      this.running = false
      this.current = null
      if (this.rerun) {
        this.rerun = false
        void this.run(false)
      }
    }
  }

  private finish(outcome: Outcome): void {
    if (outcome === 'ok') {
      this.failures = 0
      this.nextAttemptAt = 0
      this.set('idle')
      return
    }
    if (outcome === 'auth') {
      this.set('auth')
      return
    }
    this.failures += 1
    const delay = backoffDelayMs(this.failures, this.random)
    this.nextAttemptAt = this.now() + delay
    this.set(outcome === 'network' ? 'offline' : 'error')
    if (this.timer) clearTimeout(this.timer)
    this.timer = setTimeout(() => void this.run(false), delay + 50)
  }

  // --- un ciclo: subir todo lo pendiente y luego bajar el estado
  private async cycle(): Promise<Outcome> {
    for (;;) {
      const batch = await this.database.outbox
        .where('status')
        .equals('pending')
        .sortBy('seq')
        .then((rows) => rows.slice(0, BATCH))
      if (batch.length === 0) break
      const outcome = await this.push(batch)
      if (outcome !== 'ok') return outcome
    }
    return this.pull()
  }

  private async push(batch: import('../db/db').OutboxRow[]): Promise<Outcome> {
    const seqs = batch.map((e) => e.seq!)
    const pendingTotal = await this.database.outbox.where('status').anyOf('pending', 'sending').count()
    await this.database.outbox
      .where('seq')
      .anyOf(seqs)
      .modify((e) => {
        e.status = 'sending'
        e.attempts += 1
      })

    const deviceId = await this.deviceId()
    const wire: WireEvent[] = batch.map((e) => ({
      event_id: e.event_id,
      type: e.type,
      visit_id: e.visit_id,
      device_ts: e.device_ts,
      app_version: APP_VERSION,
      payload: e.payload,
    }))
    const res = await this.port.postSync(deviceId, wire, pendingTotal)

    if (res.ok) {
      const byId = new Map(res.data.results.map((r) => [r.event_id, r]))
      const stamp = new Date(this.now()).toISOString()
      await this.database.transaction('rw', this.database.outbox, async () => {
        for (const e of batch) {
          const r = byId.get(e.event_id)
          if (!r) {
            await this.database.outbox.update(e.seq!, { status: 'pending' })
          } else if (r.status === 'rejected') {
            await this.database.outbox.update(e.seq!, { status: 'rejected', reason: r.reason ?? 'rejected' })
          } else {
            await this.database.outbox.update(e.seq!, { status: 'confirmed', confirmed_at: stamp })
          }
        }
      })
      return 'ok'
    }

    if (res.kind === 'client') {
      // 4xx: el lote tiene algo que el servidor no acepta. Se aísla evento por evento para no
      // quedar atascados: el malo se rechaza y los demás siguen.
      if (batch.length > 1) {
        await this.database.outbox.where('seq').anyOf(seqs).modify({ status: 'pending' })
        for (const e of batch) {
          const outcome = await this.push([e])
          if (outcome !== 'ok') return outcome
        }
        return 'ok'
      }
      await this.database.outbox.update(batch[0]!.seq!, {
        status: 'rejected',
        reason: res.code ?? `client_${res.status}`,
      })
      return 'ok'
    }

    // Sin red, servidor caído o sesión vencida: todo vuelve a la cola, nada se pierde.
    await this.database.outbox.where('seq').anyOf(seqs).modify({ status: 'pending' })
    await this.expireOld()
    return res.kind === 'network' ? 'network' : res.kind === 'auth' ? 'auth' : 'server'
  }

  private async expireOld(): Promise<void> {
    const now = this.now()
    await this.database.outbox
      .where('status')
      .equals('pending')
      .filter((e) => e.attempts > 0 && isExpired(e.created_at, now))
      .modify({ status: 'expired' })
  }

  private async pull(): Promise<Outcome> {
    const startedAt = new Date(this.now()).toISOString()
    const cursor = (await getMeta<number>('cursor', this.database)) ?? null
    const res = await this.port.fetchState(cursor)
    if (!res.ok) return res.kind === 'network' ? 'network' : res.kind === 'auth' ? 'auth' : 'server'
    const s = res.data
    const d = this.database
    await d.transaction(
      'rw',
      [d.lines, d.products, d.institutions, d.doctors, d.visits, d.reports, d.outbox, d.meta],
      async () => {
        if (s.full) {
          await Promise.all([
            d.institutions.clear(),
            d.doctors.clear(),
            d.visits.clear(),
            d.reports.clear(),
          ])
        }
        // El catálogo de líneas y productos siempre llega completo.
        await d.lines.clear()
        await d.products.clear()
        await d.lines.bulkPut(s.lines)
        await d.products.bulkPut(s.products)
        await d.institutions.bulkPut(s.institutions)
        await d.doctors.bulkPut(s.doctors)
        await d.visits.bulkPut(s.visits as import('../db/db').VisitRow[])
        await d.reports.bulkPut((s.reports ?? []) as import('../db/db').ReportRow[])
        await setMeta('cursor', s.cursor, d)
        await setMeta('timezone', s.timezone, d)
        await setMeta('config', s.config, d)
        await setMeta('last_pull_at', s.server_time, d)
        // Lo confirmado antes de esta bajada ya está en la foto del servidor.
        await d.outbox
          .where('status')
          .equals('confirmed')
          .filter((e) => (e.confirmed_at ?? '') <= startedAt)
          .delete()
      },
    )
    return 'ok'
  }

  private async deviceId(): Promise<string> {
    let id = await getMeta<string>('device_id', this.database)
    if (!id) {
      id = newId()
      await setMeta('device_id', id, this.database)
    }
    return id
  }
}
