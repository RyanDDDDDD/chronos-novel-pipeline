import { useState } from 'react'
import {
  useSandboxDialogueTurnCount, useSetSandboxDialogueTurnCount,
} from '@/features/pipeline/queries/sandboxDialogueTurnCount'
import { useToast } from '@/shared/hooks/useToast'
import PipelineSidePanel, {
  PipelineConfigSection,
  pipelinePanelHintClass,
  pipelinePanelWideCountInputClass,
} from '@/features/pipeline/components/PipelineSidePanel'

const MIN_TURN_COUNT = 1
const MAX_TURN_COUNT = 20

function clampTurnCount(value: number): number {
  return Math.min(MAX_TURN_COUNT, Math.max(MIN_TURN_COUNT, value))
}

export default function SandboxDialogueTurnCountPanel({ novelId }: { novelId: string }) {
  const { data: turnCount } = useSandboxDialogueTurnCount(novelId)
  const save = useSetSandboxDialogueTurnCount(novelId)
  const { error: toastError } = useToast()
  const [draft, setDraft] = useState<string | null>(null)

  const displayValue = draft ?? (turnCount != null ? String(turnCount) : '')

  const commit = async () => {
    const raw = draft ?? ''
    setDraft(null)
    if (raw === '') {
      if (turnCount == null) return
      const r = await save.mutateAsync(null)
      if (!r.ok) toastError(r.error ?? '保存失败')
      return
    }
    const parsed = clampTurnCount(Number(raw))
    const r = await save.mutateAsync(parsed)
    if (!r.ok) toastError(r.error ?? '保存失败')
  }

  return (
    <PipelineSidePanel
      title="台词草稿轮数"
      hint="沙盒运行参数（按当前小说）"
      skillContent={
        <p className="text-[11px] text-[color:var(--c-text-faint)]">暂无可配置 Skill</p>
      }
    >
      <PipelineConfigSection
        title="目标行数"
        hint="正文开写前对话草稿的目标行数；留空则按本轮在场人数 + 1 自动推算"
      >
        <div className="space-y-2">
          <label className="flex items-baseline gap-1 text-sm text-[var(--c-accent)]">
            <span className="font-medium shrink-0">约</span>
            <input
              type="text"
              inputMode="numeric"
              aria-label="台词草稿目标行数"
              disabled={save.isPending}
              value={displayValue}
              placeholder="自动"
              onChange={e => setDraft(e.target.value.replace(/\D/g, ''))}
              onBlur={() => void commit()}
              onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur() }}
              className={pipelinePanelWideCountInputClass}
            />
            <span className="font-medium shrink-0">行</span>
          </label>
          <p className={pipelinePanelHintClass}>{MIN_TURN_COUNT}–{MAX_TURN_COUNT}，留空恢复自动</p>
        </div>
      </PipelineConfigSection>
    </PipelineSidePanel>
  )
}
