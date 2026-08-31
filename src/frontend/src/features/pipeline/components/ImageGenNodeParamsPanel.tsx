import { useEffect, useState } from 'react'
import { useAuthorLoopDialogueConfig, useSetAuthorLoopDialogueConfig } from '@/features/pipeline/queries/authorLoopDialogue'
import { useImageGenModelRegistry } from '@/features/pipeline/queries/modelRegistry'
import { useArtStylePresets } from '@/features/pipeline/queries/artStylePresets'
import type { LlmNodeParams } from '@/features/pipeline/utils/authorLoopDialogueConfig'
import {
  Combobox, ComboboxContent, ComboboxEmpty, ComboboxInput, ComboboxItem, ComboboxList,
} from '@/shared/components/ui/combobox'
import { Button } from '@/shared/components/ui/button'
import { Textarea } from '@/shared/components/ui/textarea'
import { HoverCard, HoverCardContent, HoverCardTrigger } from '@/shared/components/ui/hover-card'
import { cn } from '@/shared/utils/cn'

interface Props {
  nodeIds: string[]
  labels: Record<string, string>
  selectedNodeId: string | null
  novelId: string
  /** Which dialogue-config bucket the model_ref binding lives in. `import_llm_params` for the
   * skeleton tab's 立绘生成 node; `sandbox_llm_params` for the sandbox tab's 场景生图 node;
   * `llm_params` for the runtime tab's 场景生图 node. The shared style-preset / style-prompt /
   * negative-prompt fields below are global either way. */
  configKey?: 'import_llm_params' | 'sandbox_llm_params' | 'llm_params'
}

export default function ImageGenNodeParamsPanel({
  nodeIds, labels, selectedNodeId, novelId, configKey = 'import_llm_params',
}: Props) {
  const { data: cfg } = useAuthorLoopDialogueConfig(novelId)
  const save = useSetAuthorLoopDialogueConfig(novelId)
  const { data: registry } = useImageGenModelRegistry()
  const { data: presets } = useArtStylePresets()
  const [localOverrides, setLocalOverrides] = useState<Record<string, LlmNodeParams>>({})
  const [styleDraft, setStyleDraft] = useState<string | null>(null)
  const [negativeDraft, setNegativeDraft] = useState<string | null>(null)

  useEffect(() => {
    setLocalOverrides({})
    setStyleDraft(null)
    setNegativeDraft(null)
  }, [novelId])

  if (selectedNodeId === null || !nodeIds.includes(selectedNodeId)) return null
  if (!cfg) return null

  const nodeParams = (cfg.config[configKey] ?? {}) as Record<string, LlmNodeParams>
  const current: LlmNodeParams = localOverrides[selectedNodeId] ?? nodeParams[selectedNodeId] ?? {}

  const setModelRef = (modelRef: string | null) => {
    const next: LlmNodeParams = { ...current }
    if (modelRef) next.model_ref = modelRef
    else delete next.model_ref
    setLocalOverrides(prev => ({ ...prev, [selectedNodeId]: next }))
    save.mutate({ dialogue: { [configKey]: { ...nodeParams, [selectedNodeId]: next } } })
  }

  const style = styleDraft ?? cfg.config.portrait_style_prompt
  const negative = negativeDraft ?? cfg.config.portrait_negative_prompt
  const selectedPresetId = cfg.config.portrait_style_preset_id

  const commitStyle = () => {
    if (styleDraft === null || styleDraft === cfg.config.portrait_style_prompt) return
    save.mutate({ dialogue: { portrait_style_prompt: styleDraft } })
  }

  const commitNegative = () => {
    if (negativeDraft === null || negativeDraft === cfg.config.portrait_negative_prompt) return
    save.mutate({ dialogue: { portrait_negative_prompt: negativeDraft } })
  }

  const setPreset = (presetId: string) => {
    save.mutate({ dialogue: { portrait_style_preset_id: presetId } })
  }

  const models = registry?.customModels ?? []

  return (
    <div className="absolute top-3 left-3 z-10 w-72 rounded-lg border border-slate-200 bg-white shadow-float overflow-y-auto max-h-[calc(100%-1.5rem)] flex flex-col">
      <header className="px-3 py-2 border-b border-slate-100 shrink-0">
        <h2 className="text-xs font-semibold text-slate-700">生图模型 · {labels[selectedNodeId]}</h2>
        <p className="text-[11px] text-slate-400 mt-0.5">选择用于此能力的生图模型（来自服务页「生图模型」自定义条目）</p>
      </header>
      <div className="flex-1 p-3 space-y-3">
        <div className="space-y-1.5">
          <span className="text-xs font-medium text-[var(--c-text-secondary)]">画风预设</span>
          <div className="flex gap-1.5 overflow-x-auto pb-1">
            {(presets ?? []).map(preset => (
              <HoverCard key={preset.id} openDelay={150} closeDelay={0}>
                <HoverCardTrigger asChild>
                  <button
                    type="button"
                    role="button"
                    aria-label={preset.label}
                    aria-pressed={preset.id === selectedPresetId}
                    onClick={() => setPreset(preset.id)}
                    className={cn(
                      'shrink-0 w-16 rounded-md border p-1 text-center',
                      preset.id === selectedPresetId
                        ? 'border-[var(--c-accent)] bg-[var(--c-accent-subtle)]'
                        : 'border-[var(--c-border)]',
                    )}
                  >
                    <img src={preset.previewUrl} alt="" className="w-full h-16 object-cover rounded-sm" />
                    <span className="block mt-1 text-[10px] text-[var(--c-text-secondary)] truncate">{preset.label}</span>
                  </button>
                </HoverCardTrigger>
                <HoverCardContent side="right" className="w-64">
                  <img
                    src={preset.previewUrl}
                    alt={preset.label}
                    className="w-full aspect-square object-cover rounded-md"
                  />
                  <p className="mt-2 text-xs font-medium text-center text-[var(--c-text-secondary)]">{preset.label}</p>
                </HoverCardContent>
              </HoverCard>
            ))}
          </div>
        </div>
        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-[var(--c-text-secondary)]">模型</span>
            <Button
              type="button" variant="link"
              onClick={() => setModelRef(null)}
              disabled={current.model_ref === undefined}
              className="h-auto p-0 text-[10px] text-[var(--c-text-muted)] hover:text-[var(--c-text-secondary)] disabled:opacity-30"
            >
              恢复默认
            </Button>
          </div>
          {models.length === 0 ? (
            <p className="text-[11px] text-[var(--c-text-muted)]">
              还没有生图模型——去「服务」页「生图模型」tab 添加一个。
            </p>
          ) : (
            <Combobox
              items={models.map(m => m.id)}
              value={current.model_ref ?? null}
              onValueChange={(id) => { if (id) setModelRef(id) }}
              itemToStringLabel={(id) => models.find(m => m.id === id)?.label || id}
            >
              <ComboboxInput placeholder="未配置" className="font-mono text-[11px]" aria-label={`${labels[selectedNodeId]}-model-ref`} />
              <ComboboxContent>
                <ComboboxEmpty>无匹配模型</ComboboxEmpty>
                <ComboboxList>
                  {(id: string) => <ComboboxItem key={id} value={id}>{models.find(m => m.id === id)?.label || id}</ComboboxItem>}
                </ComboboxList>
              </ComboboxContent>
            </Combobox>
          )}
        </div>
        <div className="space-y-1.5">
          <span className="text-xs font-medium text-[var(--c-text-secondary)]">立绘画风（正向，全角色统一）</span>
          <Textarea
            aria-label="立绘画风（正向）"
            value={style}
            onChange={(e) => setStyleDraft(e.target.value)}
            onBlur={commitStyle}
            placeholder="在预设基础上继续补充（可留空）"
            className="text-[11px] min-h-16"
          />
        </div>
        <div className="space-y-1.5">
          <span className="text-xs font-medium text-[var(--c-text-secondary)]">立绘负面词（全角色统一）</span>
          <Textarea
            aria-label="立绘负面词"
            value={negative}
            onChange={(e) => setNegativeDraft(e.target.value)}
            onBlur={commitNegative}
            placeholder="在预设基础上继续补充（可留空）"
            className="text-[11px] min-h-16"
          />
        </div>
      </div>
    </div>
  )
}
