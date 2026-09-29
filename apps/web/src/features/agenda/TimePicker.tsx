import { useState } from 'react'
import { Chip } from '../../components/ui'
import { format12, suggestedSlots } from '../../lib/time'

interface Props {
  day: string
  tz: string
  value: string | null
  onChange: (hhmm: string) => void
}

/** Horas sugeridas cada 30 min y «Otra hora». Elegir una hora es un toque (doc 02 T3.2). */
export function TimePicker({ day, tz, value, onChange }: Props) {
  const slots = suggestedSlots(day, tz)
  const [custom, setCustom] = useState(false)
  const isCustomValue = value !== null && !slots.includes(value)

  return (
    <div>
      <div className="grid grid-cols-4 gap-2" role="group" aria-label="Hora de la visita">
        {slots.map((s) => (
          <Chip
            key={s}
            selected={value === s}
            onClick={() => {
              setCustom(false)
              onChange(s)
            }}
            className="px-1 text-[15px]"
          >
            {format12(s)}
          </Chip>
        ))}
        <Chip selected={custom || isCustomValue} onClick={() => setCustom(true)} className="px-1 text-[15px]">
          Otra…
        </Chip>
      </div>
      {(custom || isCustomValue) && (
        <div className="mt-3">
          <label className="mb-1.5 block text-sm font-semibold" htmlFor="hora-libre">
            Hora
          </label>
          <input
            id="hora-libre"
            type="time"
            step={300}
            value={value ?? ''}
            onChange={(e) => e.target.value && onChange(e.target.value)}
            className="min-h-12 w-full rounded-control border border-line bg-white px-3.5 text-base focus:border-brand"
          />
        </div>
      )}
    </div>
  )
}
