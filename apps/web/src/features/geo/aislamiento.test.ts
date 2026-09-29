import { readFileSync, readdirSync } from 'node:fs'
import { join, relative, resolve, sep } from 'node:path'
import { describe, expect, it } from 'vitest'

/**
 * T4.1 ST6: «regla de lint que prohíbe usar la Geolocation API fuera de este módulo».
 * El proyecto no usa ESLint; esta prueba cumple la misma función en cada corrida de `pnpm test`.
 * Garantiza que el GPS solo puede encenderse desde `capturar.ts` (doc 01 §9.7: ninguna posición
 * fuera de un toque de Llegué o Terminé).
 */
const src = resolve(import.meta.dirname, '../..')
const PERMITIDO = ['features', 'geo', 'capturar.ts'].join(sep)
const PROHIBIDO = /\bgeolocation\b/i

function archivos(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) => {
    const ruta = join(dir, e.name)
    if (e.isDirectory()) return archivos(ruta)
    return /\.(ts|tsx)$/.test(e.name) ? [ruta] : []
  })
}

describe('aislamiento de la Geolocation API', () => {
  it('solo features/geo/capturar.ts nombra la API de geolocalización', () => {
    const infractores = archivos(src)
      .map((f) => relative(src, f))
      .filter((rel) => rel !== PERMITIDO && !rel.endsWith('.test.ts') && !rel.endsWith('.test.tsx'))
      .filter((rel) => PROHIBIDO.test(readFileSync(join(src, rel), 'utf8').replace(/\/\*[\s\S]*?\*\/|\/\/.*$/gm, '')))
    expect(infractores).toEqual([])
  })
})
