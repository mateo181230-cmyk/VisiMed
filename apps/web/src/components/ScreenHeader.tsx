import type { ReactNode } from 'react'

export function ScreenHeader({
  title,
  subtitle,
  right,
}: {
  title: string
  subtitle?: string
  right?: ReactNode
}) {
  return (
    <header className="flex items-start justify-between gap-3 px-5 pt-[calc(16px+var(--safe-top))] pb-3">
      <div className="min-w-0">
        <h1 className="text-[32px] leading-tight font-extrabold tracking-tight break-words text-ink max-[374px]:text-2xl">{title}</h1>
        {subtitle && <p className="mt-0.5 text-base text-muted">{subtitle}</p>}
      </div>
      {right && <div className="flex shrink-0 items-center gap-2 pt-1.5">{right}</div>}
    </header>
  )
}
