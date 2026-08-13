import { useState } from 'react'
import { useAuthorLoopDialogueConfig, useSetAuthorLoopDialogueConfig } from '@/features/pipeline/queries/authorLoopDialogue'
import ReviewHookGroupSection from '@/features/pipeline/components/ReviewHookGroupSection'
import PipelineSidePanel, {
  PipelineConfigSection,
  pipelinePanelHintClass,
  pipelinePanelWideCountInputClass,
} from '@/features/pipeline/components/PipelineSidePanel'

const MIN_RECALL_COOLDOWN_TURNS = 1
const MAX_RECALL_COOLDOWN_TURNS = 50
const MIN_RECALL_TOP_K = 1
const MAX_RECALL_TOP_K = 20

function clampInRange(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

function parseCountInput(raw: string): number | null {
  const digits = raw.replace(/\D/g, '')
  if (!digits) return null
  const n = Number(digits)
  return Number.isFinite(n) ? n : null
}

export default function AuthorLoopConfigPanel({
  novelId, onSelectNode,
}: { novelId: string; onSelectNode: (id: string) => void }) {
  const { data: cfg } = useAuthorLoopDialogueConfig(novelId)
  const save = useSetAuthorLoopDialogueConfig(novelId)

  const [cooldownOverride, setCooldownOverride] = useState<number | null>(null)
  const [cooldownDraft, setCooldownDraft] = useState<string | null>(null)
  const cooldownTurns = cooldownOverride ?? cfg?.config.recall_cooldown_turns ?? 10

  const commitCooldown = (value: number) => {
    const next = clampInRange(value, MIN_RECALL_COOLDOWN_TURNS, MAX_RECALL_COOLDOWN_TURNS)
    setCooldownOverride(next)
    setCooldownDraft(null)
    save.mutate({ dialogue: { recall_cooldown_turns: next } })
  }

  const commitCooldownInput = () => {
    const parsed = parseCountInput(cooldownDraft ?? '')
    setCooldownDraft(null)
    if (parsed == null) return
    commitCooldown(parsed)
  }

  const [topKOverride, setTopKOverride] = useState<number | null>(null)
  const [topKDraft, setTopKDraft] = useState<string | null>(null)
  const topK = topKOverride ?? cfg?.config.recall_top_k ?? 5

  const commitTopK = (value: number) => {
    const next = clampInRange(value, MIN_RECALL_TOP_K, MAX_RECALL_TOP_K)
    setTopKOverride(next)
    setTopKDraft(null)
    save.mutate({ dialogue: { recall_top_k: next } })
  }

  const commitTopKInput = () => {
    const parsed = parseCountInput(topKDraft ?? '')
    setTopKDraft(null)
    if (parsed == null) return
    commitTopK(parsed)
  }

  return (
    <PipelineSidePanel
      title="主笔运行参数"
      hint="本章写作记忆召回参数（按当前小说）"
      skillContent={
        <PipelineConfigSection title="正文/章节审核" hint="候选正文写完后跑哪些判官（可拖拽到画布对应节点启用、预览规则卡片）">
          <ReviewHookGroupSection novelId={novelId} group="runtime" llmParamNodeId="review" onSelectNode={onSelectNode} />
        </PipelineConfigSection>
      }
    >
      <PipelineConfigSection
        title="跨章记忆召回"
        hint="冷却窗口：同一条设定/事件多少拍内不重复注入；Top-K：单次召回最多注入几条"
      >
        <div className="space-y-2">
          <label className="flex items-center justify-between gap-2 text-sm">
            <span className="text-[color:var(--c-text)]">冷却窗口</span>
            <input
              type="text"
              inputMode="numeric"
              aria-label="冷却窗口"
              disabled={save.isPending}
              value={cooldownDraft ?? String(cooldownTurns)}
              onFocus={() => setCooldownDraft(String(cooldownTurns))}
              onChange={e => setCooldownDraft(e.target.value.replace(/\D/g, ''))}
              onBlur={() => commitCooldownInput()}
              onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur() }}
              className={pipelinePanelWideCountInputClass}
            />
          </label>
          <label className="flex items-center justify-between gap-2 text-sm">
            <span className="text-[color:var(--c-text)]">Top-K</span>
            <input
              type="text"
              inputMode="numeric"
              aria-label="Top-K"
              disabled={save.isPending}
              value={topKDraft ?? String(topK)}
              onFocus={() => setTopKDraft(String(topK))}
              onChange={e => setTopKDraft(e.target.value.replace(/\D/g, ''))}
              onBlur={() => commitTopKInput()}
              onKeyDown={e => { if (e.key === 'Enter') e.currentTarget.blur() }}
              className={pipelinePanelWideCountInputClass}
            />
          </label>
          <p className={pipelinePanelHintClass}>
            冷却窗口 {MIN_RECALL_COOLDOWN_TURNS}–{MAX_RECALL_COOLDOWN_TURNS} 拍，Top-K {MIN_RECALL_TOP_K}–{MAX_RECALL_TOP_K}
          </p>
        </div>
      </PipelineConfigSection>
    </PipelineSidePanel>
  )
}
