import { Link } from 'react-router-dom'
import { useAuth } from '../features/auth/AuthProvider'
import { initials } from '../lib/text'

/** La cuenta se abre desde el avatar en las cuatro pantallas principales. */
export function ProfileLink({ to = '/mas' }: { to?: string }) {
  const { user } = useAuth()
  return (
    <Link
      to={to}
      aria-label="Mi cuenta"
      className="grid size-11 place-items-center rounded-full bg-brand-100 text-[15px] font-bold text-brand"
    >
      {initials(user?.full_name ?? '')}
    </Link>
  )
}
