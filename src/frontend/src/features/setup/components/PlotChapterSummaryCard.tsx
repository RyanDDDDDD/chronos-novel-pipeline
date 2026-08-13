import { Label } from '@/shared/components/ui/label'
import type { SkeletonChapterCharCounts } from '@/features/setup/utils/skeleton'

interface PlotChapterSummaryCardProps {
  coreXp: string[]
  charCounts: SkeletonChapterCharCounts | null
  recognizedCharacters: string[]
  hasOutlineText: boolean
}

export default function PlotChapterSummaryCard({
  coreXp,
  charCounts,
  recognizedCharacters,
  hasOutlineText,
}: PlotChapterSummaryCardProps) {
  const showCoreXp = coreXp.length > 0
  const showCharCounts = charCounts != null
  const showCharacters = hasOutlineText

  if (!showCoreXp && !showCharCounts && !showCharacters) return null

  return (
    <div className="rounded-lg border border-[var(--c-border)] bg-[var(--c-surface-muted)] px-3 py-2 space-y-2 text-xs text-[var(--c-text-secondary)]">
      {showCoreXp && (
        <div className="flex flex-wrap items-center gap-1.5">
          <Label className="text-xs text-[var(--c-text-muted)] shrink-0">题材基调</Label>
          {coreXp.map((xp) => (
            <span
              key={xp}
              className="text-xs px-2 py-0.5 rounded-full bg-[var(--c-tag-violet-bg)] text-[var(--c-tag-violet-text)] border border-[var(--c-tag-violet-border)]"
            >
              {xp}
            </span>
          ))}
        </div>
      )}
      {showCharCounts && (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <span className="font-medium text-[var(--c-text)] shrink-0">本章字数</span>
          <span className="tabular-nums">粗大纲 {charCounts.outlineTotal.toLocaleString('zh-CN')} 字</span>
          <span className="tabular-nums">分拍底稿 {charCounts.beatsTotal.toLocaleString('zh-CN')} 字</span>
        </div>
      )}
      {showCharacters && (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="font-medium text-[var(--c-text)] shrink-0">本章角色</span>
          <span className={recognizedCharacters.length > 0 ? '' : 'text-[var(--c-text-muted)]'}>
            {recognizedCharacters.length > 0 ? recognizedCharacters.join('、') : '无'}
          </span>
        </div>
      )}
    </div>
  )
}
