import type { ReactNode } from 'react'

interface PageHeaderProps {
  icon?: ReactNode
  title: string
  subtitle?: ReactNode
  actions?: ReactNode
  className?: string
}

/** Unified sticky title bar for top-level tab pages: icon + title/subtitle on the left, free-form actions (selects, buttons, badges) on the right. */
export default function PageHeader({ icon, title, subtitle, actions, className = '' }: PageHeaderProps) {
  return (
    <div className={`shrink-0 px-4 py-3 border-b border-[var(--c-border)] bg-[var(--c-surface)] flex flex-wrap items-center gap-3 ${className}`}>
      {icon}
      <div className="min-w-0 flex-1">
        <h1 className="text-sm font-semibold text-[var(--c-text)] truncate">{title}</h1>
        {subtitle && <p className="text-xs text-[var(--c-text-muted)] mt-0.5">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2 flex-wrap shrink-0">{actions}</div>}
    </div>
  )
}
