import { Notice } from '../../components/ui'
import { useAgenda, type VisitVM } from './useAgenda'

/** El pendiente anterior se conserva como contexto; no implica que ya se cumplió. */
export function PreviousVisitReminder({ vm }: { vm: VisitVM }) {
  const agenda = useAgenda()
  if (!['scheduled', 'in_progress'].includes(vm.visit.status)) return null
  const previous = [...agenda.visits]
    .filter((v) =>
      v.doctor_id === vm.visit.doctor_id &&
      v.primary_line_id === vm.visit.primary_line_id &&
      v.scheduled_at < vm.visit.scheduled_at && v.status === 'confirmed',
    )
    .sort((a, b) => b.scheduled_at.localeCompare(a.scheduled_at))
    .map((v) => agenda.reports.get(v.id))
    .find((r) => r?.status === 'confirmed' && r.complete &&
      r.fields.next_action?.confidence !== 'low' &&
      typeof r.fields.next_action?.value === 'string' && r.fields.next_action.value.trim())
  if (!previous) return null
  return (
    <Notice tone="info">
      <p className="font-semibold">Recuerda el pendiente de la visita anterior</p>
      <p>{String(previous.fields.next_action!.value)}</p>
    </Notice>
  )
}
