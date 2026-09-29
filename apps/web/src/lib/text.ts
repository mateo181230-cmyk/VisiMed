/** Normaliza para buscar sin distinguir tildes ni mayúsculas: «gomez» encuentra «Gómez». */
export function normalize(value: string): string {
  return value
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .trim()
}

export function matches(haystack: string, query: string): boolean {
  const q = normalize(query)
  if (!q) return true
  const h = normalize(haystack)
  return q.split(' ').every((token) => h.includes(token))
}

export function initials(fullName: string): string {
  const parts = fullName.trim().split(/\s+/).filter(Boolean)
  const first = parts[0]?.[0] ?? '?'
  const last = parts.length > 1 ? (parts[parts.length - 1]?.[0] ?? '') : ''
  return (first + last).toUpperCase()
}

/** Teléfono colombiano de 10 dígitos → E.164; deja pasar números que ya empiezan con «+». */
export function toE164(raw: string): string {
  const cleaned = raw.replace(/[\s\-().]/g, '')
  if (cleaned.startsWith('+')) return cleaned
  if (/^\d{10}$/.test(cleaned)) return `+57${cleaned}`
  if (/^57\d{10}$/.test(cleaned)) return `+${cleaned}`
  return cleaned
}
