export type LineCode = 'GASTRU' | 'RESPI' | 'OSTRU'
export type ProfileState = 'followup' | 'active' | 'explore' | 'pause'

export interface Observation {
  id: string
  line: LineCode
  day: string
  representativeId: string
  kind: 'commitment' | 'interest' | 'objection' | 'access' | 'information' | 'note'
  text: string
  confirmed: boolean
  visitId: string
}

export interface ProfileVisit {
  id: string
  day: string
  line: LineCode
  representativeId: string
  summary: string
  confirmed: boolean
  interest: number | null
}

export interface LineProfile {
  line: LineCode
  state: ProfileState
  summary: string
  nextStep: string
}

export interface DoctorProfile {
  id: string
  name: string
  specialty: string
  institution: string
  address: string
  zone: string
  representativeId: string
  color: 'blue' | 'teal' | 'purple' | 'amber'
  availability: string
  profiles: LineProfile[]
  observations: Observation[]
  visits: ProfileVisit[]
}

export interface Recommendation {
  id: string
  doctorId: string
  line: LineCode
  type: 'followup' | 'explore'
  title: string
  description: string
  shortReason: string
  reasons: { text: string; observationId: string }[]
  day: string
  time: string
  duration: number
  availabilityConfirmed: boolean
}

export interface CalendarVisit {
  title?: string | null
  id: string
  doctorId: string
  line: LineCode
  day: string
  time: string
  duration: number
  source: 'existing' | 'suggestion' | 'manual'
  recommendationId?: string
}

export interface RecommendationDecision {
  status: 'accepted' | 'dismissed'
  reason?: string
}

export interface DemoState {
  visits: CalendarVisit[]
  decisions: Record<string, RecommendationDecision>
  reviewed: string[]
}

export const LINE_NAMES: Record<LineCode, string> = {
  GASTRU: 'Gastru',
  RESPI: 'Respi',
  OSTRU: 'Ostru',
}

export const PROFILE_LABELS: Record<ProfileState, string> = {
  followup: 'Seguimiento pendiente',
  active: 'En seguimiento',
  explore: 'Por conocer',
  pause: 'Dar espacio',
}

export const OBSERVATION_LABELS: Record<Observation['kind'], string> = {
  commitment: 'Próximo paso',
  interest: 'Interés reportado',
  objection: 'Objeción reportada',
  access: 'Disponibilidad reportada',
  information: 'Información nueva',
  note: 'Nota libre',
}
