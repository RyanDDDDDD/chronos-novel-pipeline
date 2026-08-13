import { useState } from 'react'
import { useAuthorLoopDialogueConfig } from '@/features/pipeline/queries/authorLoopDialogue'
import type {
  BuildtimeReviewHookInfo, RuntimeReviewHookInfo, SetupReviewHookInfo,
} from '@/features/pipeline/utils/authorLoopDialogueConfig'
import ReviewHookPreviewDialog from '@/features/pipeline/components/ReviewHookPreviewDialog'
import { Button } from '@/shared/components/ui/button'

interface Props {
  novelId: string
  group: 'buildtime' | 'runtime' | 'setup'
  llmParamNodeId: string
  onSelectNode: (id: string) => void
}

const axisLabel: Record<'stage' | 'transition', string> = {
  stage: 'stage 轴',
  transition: '过渡轴',
}

function hasAxis(
  h: BuildtimeReviewHookInfo | RuntimeReviewHookInfo | SetupReviewHookInfo,
): h is BuildtimeReviewHookInfo {
  return 'axis' in h
}

export default function ReviewHookGroupSection({ novelId, group, llmParamNodeId, onSelectNode }: Props) {
  const { data: cfg } = useAuthorLoopDialogueConfig(novelId)
  const [previewName, setPreviewName] = useState<string | null>(null)

  const hooks = group === 'buildtime'
    ? (cfg?.buildtime_review_hooks ?? [])
    : group === 'setup'
      ? (cfg?.setup_review_hooks ?? [])
      : (cfg?.runtime_review_hooks ?? [])

  const handleDragStart = (name: string) => (e: React.DragEvent<HTMLDivElement>) => {
    e.dataTransfer.setData('application/json', JSON.stringify({ name, group }))
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-[11px] text-[color:var(--c-text-faint)]">共 {hooks.length} 项，拖进画布对应节点即启用</span>
        <Button
          type="button"
          variant="link"
          onClick={() => onSelectNode(llmParamNodeId)}
          className="h-auto p-0 text-[10px] text-[var(--c-accent)]"
        >
          采样参数
        </Button>
      </div>
      {hooks.length === 0 ? (
        <p className="text-[10px] text-[color:var(--c-text-faint)]">（无可配置 skill）</p>
      ) : (
        <div className="space-y-1.5">
          {hooks.map(h => (
            <div
              key={h.name}
              draggable
              onDragStart={handleDragStart(h.name)}
              className={`flex items-center gap-2 rounded-md border px-2 py-1.5 text-sm cursor-grab active:cursor-grabbing ${
                h.enabled
                  ? 'border-[var(--c-accent)] bg-[var(--c-accent-subtle)]'
                  : 'border-[var(--c-border)] bg-[var(--c-surface)]'
              }`}
            >
              <span className="flex-1 text-[color:var(--c-text)]">{h.display_name}</span>
              {hasAxis(h) && <span className="text-[9px] text-[color:var(--c-text-faint)]">{axisLabel[h.axis]}</span>}
              {h.enabled && <span className="text-[9px] font-medium text-[var(--c-accent-text)]">已启用</span>}
              <Button
                type="button"
                variant="ghost"
                size="sm"
                aria-label={`预览${h.display_name}`}
                onClick={() => setPreviewName(h.name)}
                className="h-auto px-1.5 py-0.5 text-[10px] text-[color:var(--c-text-muted)]"
              >
                预览
              </Button>
            </div>
          ))}
        </div>
      )}
      {previewName && (
        <ReviewHookPreviewDialog
          name={previewName}
          title={hooks.find(h => h.name === previewName)?.display_name ?? previewName}
          onClose={() => setPreviewName(null)}
        />
      )}
    </div>
  )
}
