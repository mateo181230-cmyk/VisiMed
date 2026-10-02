import { ChevronRight, Filter, Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { matches } from '../../lib/text'
import { useIntelligence } from './IntelligenceProvider'
import { Avatar, EmptyState } from './components'
import { MobileAccordion } from './MobileAccordion'
import { LINE_NAMES, PROFILE_LABELS, type LineCode, type ProfileState } from './types'

export function DoctorsScreen() {
  const { doctors, path, mode } = useIntelligence()
  const [query, setQuery] = useState('')
  const [line, setLine] = useState<LineCode | 'all'>('all')
  const [status, setStatus] = useState<ProfileState | 'all'>('all')
  const [filtersOpen, setFiltersOpen] = useState(false)
  const filtered = useMemo(
    () =>
      doctors.filter(
        (d) =>
          matches(`${d.name} ${d.specialty} ${d.institution} ${d.zone}`, query) &&
          d.profiles.some((p) => (line === 'all' || p.line === line) && (status === 'all' || p.state === status)),
      ),
    [doctors, query, line, status],
  )
  return (
    <>
      <header className="intel-mobile-heading">
        <h1>Perfiles médicos</h1>
        <p>Busca un médico y consulta su contexto.</p>
      </header>
      {mode === 'empty' ? (
        <EmptyState
          title="Todavía no hay perfiles conectados"
          description="Aquí podrás consultar el contexto de tus médicos."
        />
      ) : (
        <>
          <label className="intel-mobile-search">
            <Search size={19} />
            <input
              type="search"
              aria-label="Buscar médicos"
              placeholder="Buscar médico o institución"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </label>
          <MobileAccordion
            title={line !== 'all' || status !== 'all' ? 'Filtros activos' : 'Filtrar'}
            icon={Filter}
            open={filtersOpen}
            onToggle={() => setFiltersOpen(!filtersOpen)}
          >
            <div className="intel-form">
              <label>
                Línea
                <select
                  aria-label="Filtrar por línea"
                  value={line}
                  onChange={(e) => setLine(e.target.value as LineCode | 'all')}
                >
                  <option value="all">Todas las líneas</option>
                  {Object.entries(LINE_NAMES).map(([key, name]) => (
                    <option key={key} value={key}>
                      {name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Estado
                <select
                  aria-label="Filtrar por estado"
                  value={status}
                  onChange={(e) => setStatus(e.target.value as ProfileState | 'all')}
                >
                  <option value="all">Todos los estados</option>
                  {Object.entries(PROFILE_LABELS).map(([key, name]) => (
                    <option key={key} value={key}>
                      {name}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          </MobileAccordion>
          <p className="intel-mobile-list-count">
            {filtered.length} {filtered.length === 1 ? 'médico' : 'médicos'}
          </p>
          {filtered.length > 0 ? (
            <div className="intel-mobile-directory">
              {filtered.map((d) => (
                <Link
                  key={d.id}
                  to={path(`medicos/${d.id}${line !== 'all' ? `?linea=${line}` : ''}`)}
                  aria-label={`Abrir perfil de ${d.name}`}
                >
                  <Avatar doctor={d} />
                  <span>
                    <strong>{d.name}</strong>
                    <small>{d.institution}</small>
                  </span>
                  <ChevronRight size={18} />
                </Link>
              ))}
            </div>
          ) : (
            <div className="intel-mobile-calendar-empty">
              <h2>No encontramos coincidencias</h2>
              <p>Prueba otro nombre o ajusta los filtros.</p>
              <button
                type="button"
                className="intel-button intel-button--secondary"
                onClick={() => {
                  setQuery('')
                  setLine('all')
                  setStatus('all')
                }}
              >
                Limpiar filtros
              </button>
            </div>
          )}
        </>
      )}
    </>
  )
}
