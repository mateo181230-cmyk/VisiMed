import Dexie from 'dexie'
import { describe, expect, it } from 'vitest'
import { UnoDB, getMeta } from './db'

describe('actualización de la base local', () => {
  it('v1 → v2 olvida el cursor de bajada para volver a recibir todo (incluidas las fichas)', async () => {
    const name = `uno-upgrade-${crypto.randomUUID()}`

    // Una instalación vieja: esquema v1, con un cursor ya avanzado y datos de otra sesión.
    const old = new Dexie(name)
    old.version(1).stores({
      lines: 'id',
      products: 'id, line_id',
      institutions: 'id',
      doctors: 'id, full_name',
      visits: 'id, scheduled_at, status',
      outbox: '++seq, &event_id, status',
      meta: 'key',
    })
    await old.table('meta').bulkPut([
      { key: 'cursor', value: 987 },
      { key: 'device_id', value: 'mi-telefono' },
    ])
    old.close()

    // La app nueva abre la misma base.
    const upgraded = new UnoDB(name)
    expect(await getMeta<number>('cursor', upgraded)).toBeUndefined() // se bajará el estado completo
    expect(await getMeta<string>('device_id', upgraded)).toBe('mi-telefono') // lo demás se conserva
    expect(await upgraded.reports.count()).toBe(0)
    upgraded.close()
    await Dexie.delete(name)
  })

  it('una base nueva ya nace con la tabla de fichas', async () => {
    const fresh = new UnoDB(`uno-fresh-${crypto.randomUUID()}`)
    await fresh.reports.put({
      visit_id: 'v1',
      status: 'ready',
      complete: true,
      fields: {},
      confirmed_at: null,
      updated_at: '2026-09-29T12:00:00Z',
    })
    expect(await fresh.reports.where('status').equals('ready').count()).toBe(1)
    fresh.close()
    await Dexie.delete(fresh.name)
  })
})
