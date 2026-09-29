import { ChevronLeft, ExternalLink, LocateFixed, MapPin } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ScreenHeader } from '../../components/ScreenHeader'
import { Button, Card, Chip, Field, Notice, SectionTitle } from '../../components/ui'
import { capturarUbicacion, contextoSeguro, estadoPermiso } from './capturar'
import { RADIO_CONSULTORIO_M, RADIO_INSTITUCION_M, clasificar } from './geocerca'
import { TEXTO_ERROR, TEXTO_PERMISO, etiquetaEstado, formatearDistancia, leerCoordenadas } from './etiquetas'
import type { Clasificacion, PermisoUbicacion, Referencia, Ubicacion } from './tipos'

interface Intento {
  ubicacion: Ubicacion
  hora: string
  tipo: 'lectura' | 'referencia'
  /** Solo en las lecturas: cómo la clasificó la geocerca al medir (con la referencia y el radio de ese momento). */
  clasificacion: Clasificacion | null
}

const hora = (d: Date): string =>
  d.toLocaleTimeString('es-CO', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })

function Fila({ nombre, valor }: { nombre: string; valor: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-4 py-2">
      <dt className="text-[15px] text-muted">{nombre}</dt>
      <dd className="text-right text-[15px] font-semibold tabular-nums">{valor}</dd>
    </div>
  )
}

/**
 * Pantalla de diagnóstico (no forma parte del flujo del visitador): muestra lo que entrega el teléfono al
 * pedir la ubicación y cómo la clasificaría la geocerca. No envía ni guarda nada: ni en el servidor ni en la
 * cola de sincronización. Sirve para ver, en un lugar real, qué tan precisa es la ubicación del teléfono.
 */
export function UbicacionPrueba() {
  const [permiso, setPermiso] = useState<PermisoUbicacion>('prompt')
  const [texto, setTexto] = useState('')
  const [referencia, setReferencia] = useState<Referencia | null>(null)
  const [radio, setRadio] = useState(RADIO_INSTITUCION_M)
  const [midiendo, setMidiendo] = useState<'lectura' | 'referencia' | null>(null)
  const [segundos, setSegundos] = useState(0)
  const [historial, setHistorial] = useState<Intento[]>([])

  const inseguro = !contextoSeguro()
  const coordenadasInvalidas = texto.trim() !== '' && leerCoordenadas(texto) === null

  useEffect(() => {
    void estadoPermiso().then(setPermiso)
  }, [])

  useEffect(() => {
    if (!midiendo) return
    setSegundos(0)
    const inicio = Date.now()
    const id = setInterval(() => setSegundos(Math.floor((Date.now() - inicio) / 1000)), 250)
    return () => clearInterval(id)
  }, [midiendo])

  const medir = useCallback(
    async (para: 'lectura' | 'referencia') => {
      setMidiendo(para)
      const u = await capturarUbicacion()
      setMidiendo(null)
      setPermiso(u.permiso)
      const intento = (clasificacion: Clasificacion | null): Intento => ({
        ubicacion: u,
        hora: hora(new Date()),
        tipo: para,
        clasificacion,
      })
      if (para === 'referencia') {
        if (u.lat !== null && u.lng !== null) {
          setReferencia({ lat: u.lat, lng: u.lng })
          setTexto(`${u.lat.toFixed(6)}, ${u.lng.toFixed(6)}`)
        }
        setHistorial((h) => [intento(null), ...h].slice(0, 8))
        return
      }
      const lectura =
        u.lat !== null && u.lng !== null && u.precision_m !== null
          ? { lat: u.lat, lng: u.lng, precision_m: u.precision_m }
          : null
      setHistorial((h) => [intento(clasificar(lectura, referencia, radio)), ...h].slice(0, 8))
    },
    [radio, referencia],
  )

  const ultimo = historial[0]
  const ub = ultimo?.ubicacion
  const etiqueta = ultimo?.clasificacion
    ? etiquetaEstado(ultimo.clasificacion.estado, {
        distancia_m: ultimo.clasificacion.distancia_m,
        precision_m: ub?.precision_m ?? null,
      })
    : null

  return (
    <>
      <ScreenHeader title="Probar ubicación" subtitle="Solo diagnóstico · no se guarda nada" />
      <div className="space-y-5 px-5 pb-8">
        <Link to="/mas" className="inline-flex min-h-10 items-center gap-1 text-[15px] font-semibold text-brand">
          <ChevronLeft size={18} aria-hidden /> Más
        </Link>

        {inseguro && (
          <Notice tone="danger">
            Esta página no está en <strong>HTTPS</strong>: el navegador no entrega ubicación. Abre la app por un túnel
            HTTPS (o <code>localhost</code> en el mismo equipo).
          </Notice>
        )}

        <Card className="space-y-4 p-5">
          <SectionTitle className="px-0">1 · Lugar de referencia</SectionTitle>
          <Field
            label="Coordenadas del lugar"
            placeholder="4.67650, -74.04810"
            inputMode="decimal"
            autoComplete="off"
            value={texto}
            error={coordenadasInvalidas ? 'Usa el formato «latitud, longitud» con punto decimal.' : null}
            hint="En Google Maps toca y mantén el punto del hospital o consultorio y copia los números que aparecen."
            onChange={(e) => {
              setTexto(e.target.value)
              setReferencia(leerCoordenadas(e.target.value))
            }}
          />
          <Button
            variant="soft"
            block
            icon={<LocateFixed size={18} />}
            disabled={midiendo !== null}
            onClick={() => void medir('referencia')}
          >
            Usar mi ubicación actual como referencia
          </Button>
          <div>
            <p className="mb-2 text-sm font-semibold">Radio de la geocerca</p>
            <div className="flex gap-2">
              <Chip selected={radio === RADIO_INSTITUCION_M} onClick={() => setRadio(RADIO_INSTITUCION_M)}>
                {RADIO_INSTITUCION_M} m · hospital
              </Chip>
              <Chip selected={radio === RADIO_CONSULTORIO_M} onClick={() => setRadio(RADIO_CONSULTORIO_M)}>
                {RADIO_CONSULTORIO_M} m · consultorio
              </Chip>
            </div>
          </div>
        </Card>

        <Card className="space-y-4 p-5">
          <SectionTitle className="px-0">2 · Tomar lectura</SectionTitle>
          <p className="text-[15px] text-muted">
            Permiso de ubicación: <strong className="text-ink">{TEXTO_PERMISO[permiso]}</strong>
          </p>
          <p className="text-[15px] text-muted">
            Una sola lectura, igual que al tocar <strong className="text-ink">Llegué</strong>. Repítela en varios
            lugares para ver qué tan precisa es.
          </p>
          <Button
            size="lg"
            block
            icon={<MapPin size={20} />}
            disabled={midiendo !== null}
            onClick={() => void medir('lectura')}
          >
            {midiendo === 'lectura' ? `Buscando… ${segundos} s` : 'Tomar lectura'}
          </Button>
        </Card>

        {ub && !midiendo && (
          <Card className="space-y-3 p-5">
            <SectionTitle className="px-0">Resultado</SectionTitle>
            {etiqueta && <Notice tone={etiqueta.tono}>{etiqueta.texto}</Notice>}
            {ultimo?.tipo === 'referencia' && ub.lat !== null && (
              <Notice tone="info">
                Referencia fijada en tu ubicación actual. Aléjate y toma otra lectura para ver la distancia.
              </Notice>
            )}
            {ultimo?.clasificacion?.estado === 'sin_referencia' && (
              <Notice tone="info">Falta la referencia (paso 1) para calcular la distancia.</Notice>
            )}
            {ub.error && <Notice tone="warn">{TEXTO_ERROR[ub.error]}</Notice>}
            <dl className="divide-y divide-line">
              <Fila nombre="Precisión" valor={ub.precision_m !== null ? `± ${Math.round(ub.precision_m)} m` : '—'} />
              <Fila
                nombre="Distancia a la referencia"
                valor={
                  ultimo?.clasificacion?.distancia_m != null
                    ? formatearDistancia(ultimo.clasificacion.distancia_m)
                    : '—'
                }
              />
              <Fila nombre="Latitud" valor={ub.lat?.toFixed(6) ?? '—'} />
              <Fila nombre="Longitud" valor={ub.lng?.toFixed(6) ?? '—'} />
              <Fila nombre="Fuente" valor={ub.fuente} />
              <Fila nombre="Tardó" valor={`${(ub.duracion_ms / 1000).toFixed(1)} s`} />
              <Fila nombre="Hora de la lectura" valor={ub.fix_ts ? hora(new Date(ub.fix_ts)) : '—'} />
            </dl>
            {ub.lat !== null && ub.lng !== null && (
              <a
                href={`https://www.google.com/maps?q=${ub.lat},${ub.lng}`}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex min-h-12 items-center gap-2 text-[15px] font-semibold text-brand"
              >
                <ExternalLink size={16} aria-hidden /> Ver esta lectura en Google Maps
              </a>
            )}
          </Card>
        )}

        {historial.length > 1 && (
          <Card className="space-y-1 p-5">
            <SectionTitle className="px-0">Últimas lecturas</SectionTitle>
            <ul className="divide-y divide-line text-[15px]">
              {historial.map((h, i) => (
                <li key={i} className="flex items-baseline justify-between gap-3 py-2 tabular-nums">
                  <span className="text-muted">{h.hora}</span>
                  <span className="text-right">
                    {h.ubicacion.precision_m !== null ? `± ${Math.round(h.ubicacion.precision_m)} m` : 'sin lectura'}
                    {h.clasificacion?.distancia_m != null && ` · ${formatearDistancia(h.clasificacion.distancia_m)}`}
                    {h.tipo === 'referencia' && ' · referencia'}
                  </span>
                </li>
              ))}
            </ul>
          </Card>
        )}
      </div>
    </>
  )
}
