import type { PilotSnapshot } from '../../api/client'
import { reportIsComplete } from '../../lib/report'
import { DOCTORS, REPRESENTATIVES } from './demoData'

export const PILOT_DEMO_STORAGE_KEY = 'uno-pilot-cycle-demo-v1'
export const DEMO_VISIT_ID = 'pilot-demo-visit'
export const DEMO_DOCTOR_ID = DOCTORS[0]!.id

export function createDemoSnapshot(): PilotSnapshot {
  const visits: PilotSnapshot['visits'] = []
  const reports: PilotSnapshot['reports'] = []
  for (const doctor of DOCTORS)
    for (const v of doctor.visits) {
      const fields: PilotSnapshot['reports'][number]['fields'] = {}
      const put = (key: string, value: string | number | boolean) => {
        fields[key] = { value, confidence: 'high', source: 'call' }
      }
      put('summary', v.summary)
      put('discussion', v.summary)
      put('products_discussed', v.line === 'GASTRU' ? 'ESOMED' : v.line)
      put('visit_objective', 'Explorar necesidades y presentar la línea')
      put('visit_outcome', 'follow_up_set')
      if (v.interest !== null) put('receptiveness_score', v.interest)
      for (const o of doctor.observations.filter((o) => o.visitId === v.id)) {
        const key =
          o.kind === 'commitment'
            ? 'next_action'
            : o.kind === 'objection'
              ? 'objection'
              : o.kind === 'interest'
                ? 'doctor_interest'
                : 'new_information'
        put(key, o.text)
        if (key === 'next_action') put('commitment', o.text)
      }
      visits.push({
        id: v.id,
        doctor_id: doctor.id,
        representative_id: v.representativeId,
        primary_line_id: v.line,
        discussed_line_ids: [v.line],
        scheduled_at: `${v.day}T15:00:00Z`,
        arrived_at: `${v.day}T15:00:00Z`,
        finished_at: `${v.day}T15:08:00Z`,
        status: v.confirmed ? 'confirmed' : 'ready',
        arrival_geo_state: 'verificada',
        finish_geo_state: 'verificada',
      })
      reports.push({
        visit_id: v.id,
        status: v.confirmed ? 'confirmed' : 'ready',
        complete: reportIsComplete(fields),
        fields,
        confirmed_at: v.confirmed ? `${v.day}T15:10:00Z` : null,
        updated_at: `${v.day}T15:10:00Z`,
      })
    }
  return {
    now: '2026-09-30T21:00:00Z',
    timezone: 'America/Bogota',
    history_since: '2025-09-30T00:00:00Z',
    esomed_connected: false,
    representatives: REPRESENTATIVES,
    lines: ['GASTRU', 'RESPI', 'OSTRU'].map((code) => ({
      id: code,
      code,
      name: code,
      active: true,
    })),
    doctors: DOCTORS.map((d) => ({
      id: d.id,
      name: d.name,
      specialty: d.specialty,
      institution: d.institution,
      address: d.address,
      zone: d.zone,
      representative_id: d.representativeId,
      default_line_id: d.profiles[0]?.line ?? 'GASTRU',
      review_state: 'approved',
    })),
    visits,
    reports,
  }
}

export function readPilotDemo(): PilotSnapshot {
  try {
    const raw = sessionStorage.getItem(PILOT_DEMO_STORAGE_KEY)
    if (!raw) return createDemoSnapshot()
    const value = JSON.parse(raw) as PilotSnapshot
    if (
      !value ||
      value.now !== '2026-09-30T21:00:00Z' ||
      !Array.isArray(value.visits) ||
      !Array.isArray(value.reports) ||
      !Array.isArray(value.doctors) ||
      !Array.isArray(value.lines) ||
      !Array.isArray(value.representatives)
    )
      return createDemoSnapshot()
    // Solo recuperamos el escenario reservado. La base de ejemplo proviene del código.
    const base = createDemoSnapshot()
    const v = value.visits.find((v) => v.id === DEMO_VISIT_ID)
    const r = value.reports.find((r) => r.visit_id === DEMO_VISIT_ID)
    if (
      v &&
      v.doctor_id === DEMO_DOCTOR_ID &&
      ['in_progress', 'finished', 'in_call', 'ready', 'confirmed'].includes(v.status)
    )
      base.visits.push(v)
    if (r && r.fields && ['ready', 'confirmed'].includes(r.status)) base.reports.push(r)
    return base
  } catch {
    return createDemoSnapshot()
  }
}

export function exampleReport(date = '2026-10-07'): PilotSnapshot['reports'][number] {
  const values = {
    products_discussed: 'ESOMED',
    visit_objective: 'Presentar ESOMED y conocer su criterio de selección de IBP',
    discussion:
      'Hablamos de su uso actual de pantoprazol y del material sobre formulación de ESOMED. Preguntó por disponibilidad.',
    doctor_interest: 'La formulación de ESOMED y recibir la ficha técnica',
    doctor_disinterest: 'No le interesó cambiar de inmediato lo que prescribe',
    objection: 'Prefiere pantoprazol por costumbre; preguntó si ESOMED está disponible en su farmacia habitual',
    receptiveness_score: 4,
    doctor_reaction: 'Escuchó con atención, hizo preguntas y aceptó revisar el material',
    new_information: 'A partir de octubre atenderá los miércoles por la mañana en esta institución',
    competitor: 'pantoprazol',
    current_preference: 'pantoprazol',
    commitment: 'El visitador enviará la ficha técnica; el médico la revisará antes del seguimiento',
    next_action: 'Enviar la ficha técnica y retomar su pregunta sobre disponibilidad de ESOMED',
    next_action_date: date,
    next_action_due: date,
    samples_delivered: false,
    territory_signal: 'Pidió confirmar disponibilidad en la farmacia del sector',
    free_note: 'Coordinar las próximas visitas los miércoles por la mañana',
    visit_outcome: 'info_requested',
    summary: `Se presentó ESOMED para conocer su criterio de selección de IBP. Le interesó la formulación y pidió la ficha técnica. Usa pantoprazol por costumbre y preguntó por disponibilidad. Receptividad 4/5. Atenderá los miércoles por la mañana. El visitador enviará la ficha y hará seguimiento el ${date}; el médico revisará el material.`,
  }
  return {
    visit_id: DEMO_VISIT_ID,
    status: 'ready',
    complete: true,
    confirmed_at: null,
    updated_at: '2026-09-30T15:10:00Z',
    fields: Object.fromEntries(
      Object.entries(values).map(([key, value]) => [key, { value, confidence: 'high', source: 'call' }]),
    ),
  }
}
