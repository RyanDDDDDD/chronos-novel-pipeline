import { Loader2 } from 'lucide-react'

export type SegmentLoadingVariant = 'state' | 'suggestions' | 'default'

const VARIANT_CLASS: Record<SegmentLoadingVariant, string> = {
  state: 'text-emerald-700',
  suggestions: 'text-sky-700',
  default: 'text-slate-500',
}

/** Reusable inline loading row for segment slots awaiting async derivation/push. */
export function SegmentLoadingRow({
  label,
  variant = 'default',
  className = '',
}: {
  label: string
  variant?: SegmentLoadingVariant
  className?: string
}) {
  return (
    <div
      className={`flex items-center gap-2 text-xs py-1 ${VARIANT_CLASS[variant]} ${className}`}
      aria-busy="true"
      role="status"
    >
      <Loader2 size={14} className="animate-spin shrink-0" aria-hidden />
      <span>{label}</span>
    </div>
  )
}
