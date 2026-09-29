import { v7 as uuidv7 } from 'uuid'

/** UUIDv7: se genera en el teléfono, sin red, y es ordenable por tiempo (doc 01 §3, principio 5). */
export function newId(): string {
  return uuidv7()
}
