import { Progress } from '@/shared/components/ui/progress'

export default function ProgressBar({ index, total }: { index: number; total: number }) {
  const pct = total > 0 ? Math.min(100, Math.round((index / total) * 100)) : 0
  return (
    <div className="flex items-center gap-2">
      <Progress value={pct} className="flex-1 h-1.5" />
      <span className="shrink-0 text-[11px] text-[color:var(--c-text-muted)] tabular-nums">
        {index}/{total}
      </span>
    </div>
  )
}
