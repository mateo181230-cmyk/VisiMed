import clsx from 'clsx'
import type { ButtonHTMLAttributes, HTMLAttributes, InputHTMLAttributes, ReactNode } from 'react'

type Variant = 'primary' | 'soft' | 'ghost' | 'danger' | 'outline'

const VARIANTS: Record<Variant, string> = {
  primary: 'bg-brand text-white active:bg-brand-600 disabled:bg-brand/40',
  soft: 'bg-brand-50 text-brand active:bg-brand-100 disabled:opacity-50',
  ghost: 'bg-transparent text-brand active:bg-brand-50 disabled:opacity-50',
  danger: 'bg-danger-50 text-danger active:bg-danger-50/70 disabled:opacity-50',
  outline: 'bg-white text-ink border border-line active:bg-canvas disabled:opacity-50',
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  block?: boolean
  size?: 'md' | 'lg'
  icon?: ReactNode
}

/** Botón. Toques de al menos 48 px; el principal es de 56 px (doc 01 §8.4). */
export function Button({
  variant = 'primary',
  block,
  size = 'md',
  icon,
  className,
  children,
  type = 'button',
  ...rest
}: ButtonProps) {
  return (
    <button
      type={type}
      className={clsx(
        'inline-flex items-center justify-center gap-2 rounded-control font-semibold transition-colors select-none',
        size === 'lg' ? 'min-h-14 px-5 text-[17px]' : 'min-h-12 px-4 text-base',
        block && 'w-full',
        VARIANTS[variant],
        className,
      )}
      {...rest}
    >
      {icon}
      {children}
    </button>
  )
}

interface ChipProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  selected?: boolean
}

/** Opción seleccionable (hora, línea, motivo). */
export function Chip({ selected, className, children, type = 'button', ...rest }: ChipProps) {
  return (
    <button
      type={type}
      aria-pressed={selected}
      className={clsx(
        'min-h-12 rounded-control border px-4 text-base font-medium transition-colors',
        selected
          ? 'border-brand bg-brand text-white'
          : 'border-line bg-white text-ink active:bg-canvas',
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  )
}

export function Card({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={clsx('rounded-card bg-white shadow-[0_1px_2px_rgba(16,24,40,0.06),0_1px_1px_rgba(16,24,40,0.04)]', className)}
      {...rest}
    />
  )
}

interface FieldProps extends InputHTMLAttributes<HTMLInputElement> {
  label: string
  hint?: string
  error?: string | null
}

export function Field({ label, hint, error, id, className, ...rest }: FieldProps) {
  const fieldId = id ?? `f-${label.replace(/\W+/g, '-').toLowerCase()}`
  return (
    <div className="space-y-1.5">
      <label htmlFor={fieldId} className="block text-sm font-semibold text-ink">
        {label}
      </label>
      <input
        id={fieldId}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${fieldId}-err` : hint ? `${fieldId}-hint` : undefined}
        className={clsx(
          'min-h-12 w-full rounded-control border bg-white px-3.5 text-base placeholder:text-muted/70',
          error ? 'border-danger' : 'border-line focus:border-brand',
          className,
        )}
        {...rest}
      />
      {error ? (
        <p id={`${fieldId}-err`} role="alert" className="text-sm text-danger">
          {error}
        </p>
      ) : hint ? (
        <p id={`${fieldId}-hint`} className="text-sm text-muted">
          {hint}
        </p>
      ) : null}
    </div>
  )
}

export function SectionTitle({ children, className }: { children: ReactNode; className?: string }) {
  return <h2 className={clsx('px-1 text-[17px] font-bold text-ink', className)}>{children}</h2>
}

export function Notice({
  tone = 'info',
  children,
  className,
}: {
  tone?: 'info' | 'warn' | 'ok' | 'danger'
  children: ReactNode
  className?: string
}) {
  const tones = {
    info: 'bg-brand-50 text-navy',
    warn: 'bg-warn-50 text-warn',
    ok: 'bg-ok-50 text-ok',
    danger: 'bg-danger-50 text-danger',
  }
  return (
    <div role="status" className={clsx('rounded-control px-3.5 py-3 text-[15px] leading-snug', tones[tone], className)}>
      {children}
    </div>
  )
}

export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={clsx('animate-[skeleton_1.4s_ease-in-out_infinite] rounded-card bg-line/70', className)}
    />
  )
}
