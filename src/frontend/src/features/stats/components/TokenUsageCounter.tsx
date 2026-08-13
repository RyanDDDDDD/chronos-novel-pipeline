import {
  formatTokenCount,
  resolveTokenUsage,
  type TokenUsage,
} from '@/features/stats/utils/tokenUsage'

interface TokenUsageCounterProps {
  usage: TokenUsage | null | undefined
  title?: string
  className?: string
  /** Narrow spaces such as top columns: reduce padding and font size*/
  tight?: boolean
}

const METRICS = [
  { key: 'in' as const, label: '输入', pick: (u: TokenUsage) => u.tokens_in },
  { key: 'out' as const, label: '输出', pick: (u: TokenUsage) => u.tokens_out },
  { key: 'cached' as const, label: '缓存', pick: (u: TokenUsage) => u.tokens_cached },
]

/** Fixed outer width so stats rows (novel title + counter) align regardless of digit count. */
const WIDTH_CLASS = {
  tight: 'w-[14.5rem]',
  default: 'w-[17rem]',
} as const

function MetricCell({
  label,
  value,
  tight,
}: {
  label: string
  value: string
  tight?: boolean
}) {
  return (
    <div className={`flex flex-col justify-center min-w-0 text-right ${tight ? 'py-0.5 px-2' : 'py-2 px-3'}`}>
      <span className={`font-medium tracking-wide text-slate-400 ${tight ? 'text-[9px] leading-none' : 'text-[10px]'}`}>
        {label}
      </span>
      <span
        className={`tabular-nums leading-tight font-medium text-slate-800 ${tight ? 'text-[11px] mt-px' : 'text-xs mt-0.5'}`}
      >
        {value}
      </span>
    </div>
  )
}

export default function TokenUsageCounter({
  usage,
  title = '本次执行 token 累计',
  className = '',
  tight = false,
}: TokenUsageCounterProps) {
  const u = resolveTokenUsage(usage)

  return (
    <div
      className={`inline-flex shrink-0 max-w-full rounded-lg border border-slate-200 bg-white shadow-sm overflow-hidden ${tight ? WIDTH_CLASS.tight : WIDTH_CLASS.default} ${className}`}
      title={title}
      role="group"
      aria-label={title}
    >
      <div className="grid w-full grid-cols-3 divide-x divide-slate-100">
        {METRICS.map((m) => (
          <MetricCell
            key={m.key}
            label={m.label}
            value={formatTokenCount(m.pick(u))}
            tight={tight}
          />
        ))}
      </div>
    </div>
  )
}
