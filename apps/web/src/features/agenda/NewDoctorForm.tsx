import { useId, useState } from 'react'
import { Button, Chip, Field } from '../../components/ui'
import { newId } from '../../lib/ids'
import { normalize } from '../../lib/text'
import { enqueue } from '../../sync/outbox'
import { doctorCreated } from '../../sync/events'
import type { Agenda } from './useAgenda'

interface Props {
  agenda: Agenda
  defaultName?: string
  onCancel: () => void
  onCreated: (doctor: { id: string; name: string; lineId: string }) => void
}

/** Alta rápida de médico (doc 02 T3.4): nombre, institución, especialidad opcional y línea. */
export function NewDoctorForm({ agenda, defaultName = '', onCancel, onCreated }: Props) {
  const [name, setName] = useState(defaultName)
  const [institution, setInstitution] = useState('')
  const [specialty, setSpecialty] = useState('')
  const [lineId, setLineId] = useState<string | null>(agenda.lines.find((l) => l.active)?.id ?? null)
  const [busy, setBusy] = useState(false)
  const listId = useId()
  const lines = agenda.lines.filter((l) => l.active)
  const valid = name.trim().length >= 2 && lineId !== null

  async function save(e: React.FormEvent): Promise<void> {
    e.preventDefault()
    if (!valid || !lineId || busy) return
    setBusy(true)
    const doctorId = newId()
    // Si la institución ya existe (sin distinguir tildes) se reutiliza; si no, se crea aquí mismo.
    const typed = institution.trim()
    const existing = typed ? agenda.institutions.find((i) => normalize(i.name) === normalize(typed)) : undefined
    await enqueue(
      doctorCreated({
        doctor_id: doctorId,
        full_name: name.trim(),
        specialty: specialty.trim() || null,
        default_line_id: lineId,
        ...(existing ? { institution_id: existing.id } : typed ? { institution: { id: newId(), name: typed } } : {}),
      }),
    )
    onCreated({ id: doctorId, name: name.trim(), lineId })
  }

  return (
    <form onSubmit={save} className="space-y-4 pt-1" noValidate>
      <Field
        label="Nombre del médico"
        placeholder="Dra. Laura Méndez"
        autoFocus
        autoComplete="off"
        value={name}
        onChange={(e) => setName(e.target.value)}
      />
      <div>
        <Field
          label="Institución (opcional)"
          placeholder="Clínica Central"
          list={listId}
          autoComplete="off"
          value={institution}
          onChange={(e) => setInstitution(e.target.value)}
        />
        <datalist id={listId}>
          {agenda.institutions.map((i) => (
            <option key={i.id} value={i.name} />
          ))}
        </datalist>
      </div>
      <Field
        label="Especialidad (opcional)"
        placeholder="Medicina interna"
        autoComplete="off"
        value={specialty}
        onChange={(e) => setSpecialty(e.target.value)}
      />
      <div>
        <p className="mb-1.5 text-sm font-semibold">Línea</p>
        <div className="flex flex-wrap gap-2" role="group" aria-label="Línea del médico">
          {lines.map((l) => (
            <Chip key={l.id} selected={lineId === l.id} onClick={() => setLineId(l.id)}>
              {l.name}
            </Chip>
          ))}
        </div>
      </div>
      <div className="flex gap-2 pt-1">
        <Button variant="outline" onClick={onCancel} className="flex-1">
          Volver
        </Button>
        <Button type="submit" disabled={!valid || busy} className="flex-[2]">
          Guardar médico
        </Button>
      </div>
    </form>
  )
}
