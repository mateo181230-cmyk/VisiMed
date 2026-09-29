import { useEffect, useState } from 'react'
import { type TrainingProfile, training } from '../../api/client'
import { Sheet } from '../../components/Sheet'
import { Button, Chip, Notice } from '../../components/ui'
import { trainingError } from './labels'

/**
 * Antes de la primera visita: cómo debe tratarte el médico («doctor» o «doctora») y las condiciones
 * de la práctica (texto provisional hasta que Novamed lo apruebe).
 */
export function ConsentSheet({
  profile,
  open,
  onClose,
  onAccepted,
}: {
  profile: TrainingProfile
  open: boolean
  onClose: () => void
  onAccepted: (profile: TrainingProfile) => void
}) {
  const [salutation, setSalutation] = useState<'doctor' | 'doctora' | null>(profile.salutation ?? null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (open) setSalutation(profile.salutation ?? null)
  }, [open, profile.salutation])

  async function accept() {
    if (!salutation) return
    setSaving(true)
    setError(null)
    const res = await training.saveProfile({ salutation, accept_consent: true })
    setSaving(false)
    if (!res.ok) {
      setError(trainingError(res))
      return
    }
    onAccepted(res.data)
  }

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Antes de tu primera visita"
      footer={
        <Button block size="lg" disabled={!salutation || saving} onClick={() => void accept()}>
          {saving ? 'Guardando…' : 'Acepto y empiezo'}
        </Button>
      }
    >
      <div className="space-y-5 pt-1">
        <div className="space-y-2">
          <p className="font-semibold">¿Cómo te dice el médico?</p>
          <div className="flex gap-2">
            <Chip selected={salutation === 'doctor'} onClick={() => setSalutation('doctor')}>
              Doctor
            </Chip>
            <Chip selected={salutation === 'doctora'} onClick={() => setSalutation('doctora')}>
              Doctora
            </Chip>
          </div>
        </div>
        <div className="space-y-2">
          <p className="font-semibold">Condiciones de la práctica</p>
          <p className="text-[15px] text-muted">{profile.consent_text}</p>
        </div>
        <p className="text-sm text-muted">Usa audífonos si puedes: el médico te oye mejor y no se escucha a sí mismo.</p>
        {error && <Notice tone="danger">{error}</Notice>}
      </div>
    </Sheet>
  )
}
