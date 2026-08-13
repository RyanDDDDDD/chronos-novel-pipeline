import { useAuthorLoopDialogueConfig, useSetAuthorLoopDialogueConfig } from '@/features/pipeline/queries/authorLoopDialogue'
import type {
  BuildtimeReviewHookInfo, RuntimeReviewHookInfo, SetupReviewHookInfo,
} from '@/features/pipeline/utils/authorLoopDialogueConfig'
import StageHandles from '@/features/pipeline/components/StageHandles'
import { Button } from '@/shared/components/ui/button'

interface Data {
  label: string
  novelId: string
  group: 'buildtime' | 'runtime' | 'setup'
  selected?: boolean
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

const disabledFieldByGroup = {
  buildtime: 'disabled_buildtime_review_hooks',
  runtime: 'disabled_runtime_review_hooks',
  setup: 'disabled_setup_review_hooks',
} as const

export default function ReviewSkillDropNode({ data }: { data: Data }) {
  const { data: cfg } = useAuthorLoopDialogueConfig(data.novelId)
  const save = useSetAuthorLoopDialogueConfig(data.novelId)

  const active = data.group === 'buildtime'
    ? (cfg?.buildtime_review_hooks ?? []).filter(h => h.enabled)
    : data.group === 'setup'
      ? (cfg?.setup_review_hooks ?? []).filter(h => h.enabled)
      : (cfg?.runtime_review_hooks ?? []).filter(h => h.enabled)

  const disabledField = disabledFieldByGroup[data.group]
  const disabled = cfg?.config[disabledField] ?? []

  const enableSkill = (name: string) => {
    if (disabled.includes(name)) {
      save.mutate({ dialogue: { [disabledField]: disabled.filter(n => n !== name) } })
    }
  }

  const removeSkill = (name: string) => {
    save.mutate({ dialogue: { [disabledField]: [...disabled, name] } })
  }

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault()
    let payload: { name?: string; group?: string }
    try {
      payload = JSON.parse(e.dataTransfer.getData('application/json'))
    } catch {
      return
    }
    if (payload.group !== data.group || !payload.name) return
    enableSkill(payload.name)
  }

  const selectedStyle = data.selected ? ' ring-2 ring-[var(--c-accent)] ring-offset-1' : ''
  return (
    <div
      data-testid="review-skill-drop-node"
      onDragOver={e => e.preventDefault()}
      onDrop={handleDrop}
      className={`rounded-lg min-w-[9rem] border border-[var(--c-border)] bg-[var(--c-surface)]${selectedStyle}`}
    >
      <StageHandles />
      <div className="px-3 pt-2.5 pb-2 text-xs text-[color:var(--c-text-faint)]">
        <div className="font-medium text-[color:var(--c-text-secondary)] mb-1">{data.label}</div>
        {active.length === 0 ? (
          <p className="text-[10px] text-[color:var(--c-text-faint)]">（无生效 skill，拖一个进来）</p>
        ) : (
          <ul className="space-y-1">
            {active.map(h => (
              <li key={h.name} className="flex items-center justify-between gap-2">
                <span className="text-[11px] text-[color:var(--c-text-secondary)]">{h.display_name}</span>
                {hasAxis(h) && <span className="text-[9px] text-[color:var(--c-text-faint)]">{axisLabel[h.axis]}</span>}
                <Button
                  type="button"
                  variant="ghost"
                  size="icon"
                  aria-label={`删除${h.display_name}`}
                  onClick={e => { e.stopPropagation(); removeSkill(h.name) }}
                  disabled={save.isPending}
                  className="h-auto w-auto p-0.5 text-[color:var(--c-text-faint)] hover:text-red-500 disabled:opacity-40"
                >
                  ×
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}
