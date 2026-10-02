import { LogOut, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthProvider'
import { useOutboxCounts } from '../../sync/SyncProvider'
import { Sheet } from '../../components/Sheet'
import { Button, Notice } from '../../components/ui'
import './dashboard.css'

export function AdminAccount() {
  const { user, signOut } = useAuth()
  const { pending, rejected, expired } = useOutboxCounts()
  const navigate = useNavigate()
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const unsent = pending + rejected + expired
  async function logout() {
    setBusy(true)
    setError('')
    try { await signOut(); navigate('/login', { replace: true }) }
    catch { setError('No se pudo cerrar la sesión. Inténtalo de nuevo.'); setBusy(false) }
  }
  return <section className="ad-dashboard"><header className="ad-heading"><div><span className="ad-eyebrow">ADMINISTRACIÓN</span><h1>Mi cuenta<span>.</span></h1><p>Tu acceso al panel del equipo y al entrenamiento.</p></div></header><div className="ad-card" style={{maxWidth:650}}><div className="ad-card-heading"><h2>{user?.full_name}</h2><ShieldCheck size={25}/></div><dl className="ad-account-details"><div><dt>Celular</dt><dd>{user?.phone}</dd></div><div><dt>Perfil de acceso</dt><dd>{user?.role === 'admin' ? 'Administrador' : user?.role === 'manager' ? 'Gerencia' : 'Visitador'}</dd></div><div><dt>Zona horaria</dt><dd>{user?.timezone}</dd></div></dl><div className="ad-account-actions"><Link className="intel-button intel-button--secondary" to="/inteligencia/resumen">Volver al dashboard</Link>{user?.role === 'admin' && <Link className="intel-button intel-button--secondary" to="/admin/training">Abrir Training Builder</Link>}<Button variant="danger" icon={<LogOut size={18}/>} onClick={() => setConfirming(true)}>Cerrar sesión</Button></div></div><Sheet open={confirming} onClose={() => {if(!busy)setConfirming(false)}} title="¿Cerrar sesión?"><div className="space-y-4 pt-2">{unsent>0?<Notice tone="warn">Hay {unsent} cambios pendientes de envío. Cerrar sesión ahora los eliminará de este dispositivo.</Notice>:<p>Podrás volver a entrar con tu celular y PIN.</p>}{error&&<p role="alert">{error}</p>}<div className="flex gap-3 pb-3"><Button variant="outline" disabled={busy} onClick={() => setConfirming(false)}>Cancelar</Button><Button variant="danger" disabled={busy} onClick={() => void logout()}>{busy?'Cerrando sesión…':'Confirmar cierre de sesión'}</Button></div></div></Sheet></section>
}
