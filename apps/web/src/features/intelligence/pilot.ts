import type { PilotSnapshot } from '../../api/client'
import { addDays, dateKey, hhmm } from '../../lib/time'
import type { CalendarVisit, DoctorProfile, LineCode, Observation, Recommendation } from './types'

export interface PilotAlert {
  id: string
  kind: 'short_visit' | 'stale_doctor' | 'repetitive' | 'incomplete' | 'location' | 'atypical'
  doctorId: string
  visitId?: string
  title: string
  detail: string
}

interface CountedSignal {
  label: string
  count: number
}

export interface PilotAnalysis {
  doctors: DoctorProfile[]
  recommendations: Recommendation[]
  visits: CalendarVisit[]
  alerts: PilotAlert[]
  metrics: {
    completed: number
    doctorsVisited: number
    confirmed: number
    toConfirm: number
    averageMinutes: number | null
    verified: number
    byRep: {
      id: string
      name: string
      planned: number
      completed: number
      compliance: number | null
    }[]
    daily: { day: string; completed: number }[]
  }
  insights: {
    objections: CountedSignal[]
    products: CountedSignal[]
    interests: CountedSignal[]
    productInterest: { label: string; reports: number; interested: number }[]
    competitors: CountedSignal[]
    receptive: {
      doctorId: string
      name: string
      score: number
      reports: number
    }[]
    territories: { zone: string; reports: number; signals: string[] }[]
  }
}

const fold = (s: string) =>
  s
    .toLocaleLowerCase('es')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .trim()
const isLine = (s: string): s is LineCode => ['GASTRU', 'RESPI', 'OSTRU'].includes(s)
const score = (v: unknown): v is number => typeof v === 'number' && Number.isInteger(v) && v >= 1 && v <= 5
const noSignal = (s: string) =>
  /^(no (hubo|hay|menciono|entrego|quedaron|manifesto|mostro interes|le intereso|tiene interes|se acordo)|ningun|nada|sin )/.test(
    fold(s),
  )
const objectionTopics = (s: string): string[] => {
  const value = fold(s)
  const topics = [
    [/precio|costo|coste|car[oa]\b|costoso|cobertura/, 'Precio o cobertura'],
    [/disponibilidad|inventario|farmacia|agotad|desabastecimiento/, 'Disponibilidad'],
    [/evidencia|estudio|informacion|ficha tecnica|material/, 'Información o evidencia'],
    [/prefier|preferencia|costumbre|cambiar|ya usa/, 'Preferencia por el tratamiento actual'],
    [/competencia|otro laboratorio|otra marca/, 'Competencia'],
    [/tiempo|agenda|ocupad|cirugia/, 'Tiempo para la visita'],
  ] as const
  const found = topics.filter(([pattern]) => pattern.test(value)).map(([, label]) => label)
  return found.length ? found : [s]
}

/** Reglas transparentes del piloto, con evidencia de cada visita; no requieren un modelo entrenado. */
export function analyzePilot(snapshot: PilotSnapshot, scope = 'all', periodDays = 30): PilotAnalysis {
  const today = dateKey(snapshot.now, snapshot.timezone)
  const periodStart = addDays(today, 1 - periodDays)
  const now = Date.parse(snapshot.now)
  const lines = new Map(snapshot.lines.map((l) => [l.id, l.code]))
  const reports = new Map(snapshot.reports.map((r) => [r.visit_id, r]))
  const rawVisits = snapshot.visits.filter((v) => scope === 'all' || v.representative_id === scope)
  const field = (visitId: string, key: string): string | number | boolean | null => {
    const entry = reports.get(visitId)?.fields[key]
    return entry?.confidence === 'low' ? null : (entry?.value ?? null)
  }
  const text = (visitId: string, key: string) => {
    const v = field(visitId, key)
    return typeof v === 'string' ? v : ''
  }
  const completed = (v: (typeof rawVisits)[number]) =>
    !!v.finished_at &&
    Date.parse(v.finished_at) <= now &&
    v.status !== 'not_done' &&
    field(v.id, 'visit_outcome') !== 'not_attended'
  const discussedLines = (v: (typeof rawVisits)[number]) => {
    if (v.discussed_line_ids?.length) return v.discussed_line_ids
    const products = text(v.id, 'products_discussed')
    if (!products) return []
    const words = ` ${fold(products).replace(/[^a-z0-9]+/g, ' ')} `
    return snapshot.lines
      .filter((l) => [l.code, l.name].some((alias) => words.includes(` ${fold(alias)} `)))
      .map((l) => l.id)
  }
  const dayOf = (v: (typeof rawVisits)[number]) => dateKey(v.finished_at ?? v.scheduled_at, snapshot.timezone)
  const period = rawVisits.filter((v) => dayOf(v) >= periodStart && dayOf(v) <= today)
  const done = period.filter(completed)
  const confirmed = done.filter((v) => reports.get(v.id)?.status === 'confirmed')
  const allDone = rawVisits.filter(completed).sort((a, b) => (b.finished_at ?? '').localeCompare(a.finished_at ?? ''))
  const alerts: PilotAlert[] = []
  const recommendations: Recommendation[] = []
  const rawDoctors = snapshot.doctors.filter(
    (d) => scope === 'all' || d.representative_id === scope || rawVisits.some((v) => v.doctor_id === d.id),
  )
  const doctors: DoctorProfile[] = rawDoctors.map((d, index) => {
    const doctorVisits = allDone.filter((v) => v.doctor_id === d.id)
    const observations: Observation[] = []
    const profileVisits = doctorVisits.flatMap((v) => {
      const actual = discussedLines(v)
      const line = lines.get(actual[0] ?? v.primary_line_id)
      if (!line || !isLine(line) || !reports.has(v.id)) return []
      const isConfirmed = reports.get(v.id)?.status === 'confirmed'
      for (const [key, kind] of [
        ['commitment', 'commitment'],
        ['next_action', 'commitment'],
        ['doctor_interest', 'interest'],
        ['objection', 'objection'],
        ['new_information', 'information'],
        ['free_note', 'note'],
      ] as const) {
        const value = text(v.id, key)
        if (value && !noSignal(value))
          observations.push({
            id: `${v.id}-${key}`,
            line,
            day: dayOf(v),
            representativeId: v.representative_id,
            kind,
            text: value,
            confirmed: isConfirmed,
            visitId: v.id,
          })
      }
      const level = field(v.id, 'receptiveness_score')
      return [
        {
          id: v.id,
          day: dayOf(v),
          line,
          representativeId: v.representative_id,
          summary:
            (actual.length ? '' : `Línea planificada: ${line}; línea presentada por verificar. `) +
            (text(v.id, 'summary') || text(v.id, 'discussion') || 'Reporte pendiente de completar'),
          confirmed: isConfirmed,
          interest: score(level) ? level : null,
        },
      ]
    })
    const activeLines = new Set(
      doctorVisits
        .flatMap(discussedLines)
        .map((id) => lines.get(id))
        .filter((c): c is LineCode => !!c && isLine(c)),
    )
    const defaultLine = d.default_line_id ? lines.get(d.default_line_id) : null
    if (defaultLine && isLine(defaultLine)) activeLines.add(defaultLine)
    const profiles = [...activeLines].map((line) => {
      const last = doctorVisits.find(
        (v) => discussedLines(v).some((id) => lines.get(id) === line) && reports.get(v.id)?.status === 'confirmed',
      )
      const next = last ? text(last.id, 'next_action') : ''
      const due = last ? text(last.id, 'next_action_due') : ''
      const planned = rawVisits.some(
        (v) =>
          v.doctor_id === d.id &&
          lines.get(v.primary_line_id) === line &&
          (v.status === 'in_progress' || (v.status === 'scheduled' && Date.parse(v.scheduled_at) >= now)),
      )
      if (last && next && !noSignal(next) && reports.get(last.id)?.complete && !planned) {
        const observationId = `${last.id}-next_action`
        recommendations.push({
          id: `followup-${last.id}${discussedLines(last).length > 1 ? `-${line}` : ''}`,
          doctorId: d.id,
          line,
          type: 'followup',
          title: `Continuar con ${text(last.id, 'products_discussed') || line}`,
          description: next,
          shortReason: due ? `Seguimiento reportado para ${due}` : 'Próximo paso confirmado; falta acordar la fecha',
          reasons: [{ text: next, observationId }],
          day: due && due > today ? due : addDays(today, 1),
          time: '09:00',
          duration: 15,
          availabilityConfirmed: false,
        })
      }
      return {
        line,
        state: next ? ('followup' as const) : last ? ('active' as const) : ('explore' as const),
        summary: last
          ? text(last.id, 'summary') || text(last.id, 'discussion')
          : 'Sin reporte confirmado para esta línea',
        nextStep: next || 'Explorar necesidades y acordar un próximo paso con el médico',
      }
    })
    const latest = doctorVisits[0]
    if (!latest || dayOf(latest) < addDays(today, -90))
      alerts.push({
        id: `stale-${d.id}`,
        kind: 'stale_doctor',
        doctorId: d.id,
        title: 'Contexto del médico por actualizar',
        detail: latest
          ? `Última visita registrada: ${dayOf(latest)}. Más de 90 días sin contacto.`
          : 'Sin visita registrada en el historial disponible.',
      })
    if (d.review_state === 'pending_review')
      alerts.push({
        id: `review-${d.id}`,
        kind: 'stale_doctor',
        doctorId: d.id,
        title: 'Datos del médico por verificar',
        detail: 'El alta del médico sigue pendiente de revisión.',
      })
    if (
      (!latest || dayOf(latest) < addDays(today, -90)) &&
      !recommendations.some((r) => r.doctorId === d.id) &&
      defaultLine &&
      isLine(defaultLine) &&
      !rawVisits.some((v) => v.doctor_id === d.id && v.status === 'scheduled' && Date.parse(v.scheduled_at) >= now)
    )
      recommendations.push({
        id: `refresh-${d.id}`,
        doctorId: d.id,
        line: defaultLine,
        type: 'explore',
        title: 'Actualizar el contexto del médico',
        description: 'Confirmar institución, necesidades actuales y acordar el próximo paso.',
        shortReason: latest ? 'Más de 90 días desde la última visita' : 'Sin historial de visita disponible',
        reasons: [],
        day: addDays(today, 1),
        time: '09:00',
        duration: 15,
        availabilityConfirmed: false,
      })
    return {
      id: d.id,
      name: d.name,
      specialty: d.specialty || 'Sin especialidad registrada',
      institution: d.institution || 'Sin institución registrada',
      address: d.address || 'Sin dirección registrada',
      zone: d.zone || 'Sin territorio registrado',
      representativeId: d.representative_id,
      color: (['blue', 'teal', 'purple', 'amber'] as const)[index % 4]!,
      availability: 'Coordinar disponibilidad con el consultorio',
      profiles,
      observations,
      visits: profileVisits,
    }
  })
  for (const v of done) {
    const duration =
      v.arrived_at && v.finished_at ? (Date.parse(v.finished_at) - Date.parse(v.arrived_at)) / 60_000 : null
    if (duration !== null && duration >= 0 && duration < 3)
      alerts.push({
        id: `short-${v.id}`,
        kind: 'short_visit',
        doctorId: v.doctor_id,
        visitId: v.id,
        title: 'Visita de menos de 3 minutos',
        detail: `${duration.toFixed(1)} minutos entre llegada y salida. Revisar el contexto.`,
      })
    if (duration !== null && (duration < 0 || duration > 180))
      alerts.push({
        id: `atypical-${v.id}`,
        kind: 'atypical',
        doctorId: v.doctor_id,
        visitId: v.id,
        title: 'Duración atípica',
        detail:
          duration < 0
            ? 'La salida aparece antes de la llegada.'
            : 'Más de 3 horas entre llegada y salida; comprobar un posible cierre tardío.',
      })
    if (!reports.get(v.id)?.complete)
      alerts.push({
        id: `incomplete-${v.id}`,
        kind: 'incomplete',
        doctorId: v.doctor_id,
        visitId: v.id,
        title: 'Información incompleta',
        detail: reports.has(v.id) ? 'Faltan datos esenciales de la entrevista.' : 'La visita aún no tiene reporte.',
      })
    if (v.arrival_geo_state !== 'verificada' || v.finish_geo_state !== 'verificada')
      alerts.push({
        id: `geo-${v.id}`,
        kind: 'location',
        doctorId: v.doctor_id,
        visitId: v.id,
        title: 'Ubicación por revisar',
        detail: `Llegada: ${v.arrival_geo_state ?? 'sin registro'} · salida: ${v.finish_geo_state ?? 'sin registro'}.`,
      })
  }
  const recentByDoctorLine = new Map<string, typeof done>()
  for (const v of done.filter((v) => dayOf(v) >= addDays(today, -6))) {
    for (const lineId of discussedLines(v).length ? discussedLines(v) : [v.primary_line_id]) {
      const key = `${v.doctor_id}-${lineId}`
      recentByDoctorLine.set(key, [...(recentByDoctorLine.get(key) ?? []), v])
    }
  }
  for (const [key, list] of recentByDoctorLine)
    if (list.length >= 3)
      alerts.push({
        id: `repeated-${key}`,
        kind: 'repetitive',
        doctorId: list[0]!.doctor_id,
        title: 'Visitas frecuentes al mismo médico',
        detail: `${list.length} visitas de la misma línea en 7 días. Revisar propósito y avances.`,
      })
  // Insights solo con reportes confirmados; cada conteo representa visitas, no menciones.
  function counts(key: string, split = false, classify?: (s: string) => string[]): CountedSignal[] {
    const values = new Map<string, CountedSignal>()
    for (const v of confirmed) {
      const raw = text(v.id, key)
      if (!raw || noSignal(raw)) continue
      const unique = new Map(
        (classify ? classify(raw) : split ? raw.split(/[,;]/) : [raw])
          .filter((s) => s.trim())
          .map((s) => [fold(s), s.trim()]),
      )
      for (const [normal, label] of unique) {
        const prior = values.get(normal)
        values.set(normal, {
          label: prior?.label ?? label,
          count: (prior?.count ?? 0) + 1,
        })
      }
    }
    return [...values.values()].sort((a, b) => b.count - a.count)
  }
  const receptivity = new Map<string, number[]>()
  const territory = new Map<string, { zone: string; reports: number; signals: string[] }>()
  const productInterest = new Map<string, { label: string; reports: number; interested: number }>()
  for (const v of confirmed) {
    const products = [
      ...new Map(
        text(v.id, 'products_discussed')
          .split(/[,;]/)
          .map((p) => p.trim())
          .filter(Boolean)
          .map((p) => [fold(p), p]),
      ).values(),
    ]
    const interest = text(v.id, 'doctor_interest')
    for (const product of products) {
      const normal = fold(product)
      const item = productInterest.get(normal) ?? {
        label: product,
        reports: 0,
        interested: 0,
      }
      item.reports += 1
      if (interest && !noSignal(interest) && (products.length === 1 || fold(interest).includes(normal)))
        item.interested += 1
      productInterest.set(normal, item)
    }
    const level = field(v.id, 'receptiveness_score')
    if (score(level)) receptivity.set(v.doctor_id, [...(receptivity.get(v.doctor_id) ?? []), level])
    const zone = doctors.find((d) => d.id === v.doctor_id)?.zone ?? 'Sin territorio registrado'
    const group = territory.get(zone) ?? { zone, reports: 0, signals: [] }
    group.reports += 1
    const signal = text(v.id, 'territory_signal')
    if (signal && !noSignal(signal)) group.signals.push(signal)
    territory.set(zone, group)
  }
  const durations = done.flatMap((v) => {
    if (!v.arrived_at || !v.finished_at) return []
    const min = (Date.parse(v.finished_at) - Date.parse(v.arrived_at)) / 60_000
    return min >= 0 && min <= 180 ? [min] : []
  })
  const daily = new Map<string, number>()
  done.forEach((v) => daily.set(dayOf(v), (daily.get(dayOf(v)) ?? 0) + 1))
  return {
    doctors,
    recommendations: recommendations.sort((a, b) => a.day.localeCompare(b.day)),
    visits: rawVisits
      .filter((v) => v.status === 'scheduled' || v.status === 'in_progress')
      .flatMap((v) => {
        const line = lines.get(v.primary_line_id)
        return line && isLine(line)
          ? [
              {
                id: v.id,
                title: v.title,
                doctorId: v.doctor_id,
                line,
                day: dateKey(v.scheduled_at, snapshot.timezone),
                time: hhmm(v.scheduled_at, snapshot.timezone),
                duration: 15,
                source: 'existing' as const,
              },
            ]
          : []
      }),
    alerts,
    metrics: {
      completed: done.length,
      doctorsVisited: new Set(done.map((v) => v.doctor_id)).size,
      confirmed: confirmed.length,
      toConfirm: done.filter((v) => reports.get(v.id)?.status === 'ready').length,
      averageMinutes: durations.length ? durations.reduce((a, b) => a + b, 0) / durations.length : null,
      verified: done.filter((v) => v.arrival_geo_state === 'verificada' && v.finish_geo_state === 'verificada').length,
      daily: [...daily].map(([day, count]) => ({ day, completed: count })).sort((a, b) => b.day.localeCompare(a.day)),
      byRep: snapshot.representatives
        .filter((r) => scope === 'all' || r.id === scope)
        .map((r) => {
          const planned = rawVisits.filter(
            (v) =>
              v.representative_id === r.id &&
              dateKey(v.scheduled_at, snapshot.timezone) >= periodStart &&
              Date.parse(v.scheduled_at) <= now,
          ).length
          const count = rawVisits.filter(
            (v) =>
              v.representative_id === r.id &&
              dateKey(v.scheduled_at, snapshot.timezone) >= periodStart &&
              Date.parse(v.scheduled_at) <= now &&
              completed(v),
          ).length
          return {
            ...r,
            planned,
            completed: count,
            compliance: planned ? Math.round((count / planned) * 100) : null,
          }
        }),
    },
    insights: {
      objections: counts('objection', false, objectionTopics),
      products: counts('products_discussed', true),
      interests: counts('doctor_interest'),
      productInterest: [...productInterest.values()].sort((a, b) => b.interested - a.interested),
      competitors: counts('competitor', true),
      receptive: [...receptivity]
        .map(([doctorId, levels]) => ({
          doctorId,
          name: doctors.find((d) => d.id === doctorId)?.name ?? 'Médico',
          score: levels.reduce((a, b) => a + b, 0) / levels.length,
          reports: levels.length,
        }))
        .sort((a, b) => b.score - a.score),
      territories: [...territory.values()],
    },
  }
}
