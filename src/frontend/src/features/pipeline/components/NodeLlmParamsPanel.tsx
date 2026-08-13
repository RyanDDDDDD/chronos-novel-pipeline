import { useEffect, useState } from 'react'
import { useAuthorLoopDialogueConfig, useSetAuthorLoopDialogueConfig } from '@/features/pipeline/queries/authorLoopDialogue'
import { useModelRegistry } from '@/features/pipeline/queries/modelRegistry'
import { resolveModelEntryLabel, resolveModelRegistryLabel } from '@/features/services/utils/llmCatalog'
import type { LlmNodeParams, LlmParamKey, ThinkingEffort } from '@/features/pipeline/utils/authorLoopDialogueConfig'
import { defaultEnableThinkingForNode } from '@/features/pipeline/utils/authorLoopDialogueConfig'
import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
} from '@/shared/components/ui/combobox'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/shared/components/ui/select'
import { Switch } from '@/shared/components/ui/switch'
import { Button } from '@/shared/components/ui/button'

const PARAM_META: { key: LlmParamKey; label: string; min: number; max: number; step: number }[] = [
  { key: 'temperature', label: 'temperature', min: 0, max: 2, step: 0.05 },
  { key: 'top_p', label: 'top_p', min: 0, max: 1, step: 0.05 },
  { key: 'frequency_penalty', label: 'frequency_penalty', min: -2, max: 2, step: 0.05 },
  { key: 'presence_penalty', label: 'presence_penalty', min: -2, max: 2, step: 0.05 },
]

const THINKING_EFFORT_OPTIONS: { value: ThinkingEffort; label: string }[] = [
  { value: 'low', label: 'low' },
  { value: 'medium', label: 'medium' },
  { value: 'high', label: 'high' },
]

interface Props {
  nodeIds: string[]
  labels: Record<string, string>
  configKey: 'llm_params' | 'sandbox_llm_params' | 'import_llm_params'
  title: string
  hint: string
  selectedNodeId: string | null
  novelId: string
  styleGuardNodeIds?: Set<string>
}

export default function NodeLlmParamsPanel({
  nodeIds, labels, configKey, title, hint, selectedNodeId, novelId, styleGuardNodeIds = new Set(),
}: Props) {
  const { data: cfg } = useAuthorLoopDialogueConfig(novelId)
  const save = useSetAuthorLoopDialogueConfig(novelId)
  const { data: registry } = useModelRegistry()
  // Local override per node id, keyed like nodeParams -- persists past the save's refetch
  // (never reset from server) so a just-clicked checkbox/select/slider shows its new value
  // immediately instead of snapping back to the stale cfg until the PUT round-trip resolves
  // (same pattern as PipelineConfigPanel's target-words/character-count overrides).
  const [localOverrides, setLocalOverrides] = useState<Record<string, LlmNodeParams>>({})

  // Panel instance stays mounted across novel switches (same pipeline tab); drop stale per-node
  // edits so a new novel's empty prefs are not masked by the previous novel's localOverrides.
  useEffect(() => {
    setLocalOverrides({})
  }, [novelId, configKey])

  if (selectedNodeId === null || !nodeIds.includes(selectedNodeId)) return null
  if (!cfg) return null

  const nodeParams = (cfg.config[configKey] ?? {}) as Record<string, LlmNodeParams>
  const current: LlmNodeParams = localOverrides[selectedNodeId] ?? nodeParams[selectedNodeId] ?? {}
  const nodeDefaultThinking = defaultEnableThinkingForNode(selectedNodeId)
  const effectiveThinking = current.enable_thinking ?? nodeDefaultThinking

  const commit = (nextNode: LlmNodeParams) => {
    setLocalOverrides(prev => ({ ...prev, [selectedNodeId]: nextNode }))
    save.mutate({ dialogue: { [configKey]: { ...nodeParams, [selectedNodeId]: nextNode } } })
  }

  const setParam = (key: LlmParamKey, value: number | null) => {
    const nextNode: LlmNodeParams = { ...current }
    if (value === null) delete nextNode[key]
    else nextNode[key] = value
    commit(nextNode)
  }

  const setThinking = (enable: boolean, effort: ThinkingEffort | null) => {
    const nextNode: LlmNodeParams = { ...current }
    if (enable) {
      nextNode.enable_thinking = true
      nextNode.thinking_effort = effort ?? current.thinking_effort ?? 'medium'
    } else {
      nextNode.enable_thinking = false
      delete nextNode.thinking_effort
    }
    commit(nextNode)
  }

  const setModelRef = (modelRef: string | null) => {
    const nextNode: LlmNodeParams = { ...current }
    if (modelRef) nextNode.model_ref = modelRef
    else delete nextNode.model_ref
    commit(nextNode)
  }

  const setStyleGuardDisabled = (disabled: boolean | null) => {
    const nextNode: LlmNodeParams = { ...current }
    if (disabled === null) delete nextNode.disable_style_guard
    else nextNode.disable_style_guard = disabled
    commit(nextNode)
  }

  const setConcurrent = (value: boolean | null) => {
    const nextNode: LlmNodeParams = { ...current }
    if (value === null) delete nextNode.concurrent
    else nextNode.concurrent = value
    commit(nextNode)
  }

  return (
    <div className="absolute top-3 left-3 z-10 w-72 rounded-lg border border-slate-200 bg-white shadow-float overflow-y-auto max-h-[calc(100%-1.5rem)] flex flex-col">
      <header className="px-3 py-2 border-b border-slate-100 shrink-0">
        <h2 className="text-xs font-semibold text-slate-700">{title} · {labels[selectedNodeId]}</h2>
        <p className="text-[11px] text-slate-400 mt-0.5">{hint}</p>
      </header>
      <div className="flex-1 p-3 space-y-4">
        {PARAM_META.map(({ key, label, min, max, step }) => {
          const value = current[key]
          return (
            <div key={key} className="space-y-1">
              <div className="flex items-center justify-between">
                <span className="text-xs font-medium text-slate-700">{label}</span>
                <Button
                  type="button"
                  variant="link"
                  onClick={() => setParam(key, null)}
                  disabled={value === undefined}
                  className="h-auto p-0 text-[10px] text-slate-400 hover:text-slate-600 disabled:opacity-30"
                >
                  恢复默认
                </Button>
              </div>
              <input
                type="range"
                min={min}
                max={max}
                step={step}
                value={value ?? (min + max) / 2}
                onChange={e => setParam(key, Number(e.target.value))}
                aria-label={`${labels[selectedNodeId]} ${label}`}
                className="w-full h-1.5 accent-violet-600 cursor-pointer"
              />
              <div className="text-[11px] text-slate-400 tabular-nums">
                {value === undefined ? '未设置（沿用全局默认）' : value.toFixed(2)}
              </div>
            </div>
          )
        })}
        <div className="space-y-1.5 pt-2 border-t border-slate-100">
          <span className="text-xs font-medium text-slate-700">enable thinking</span>
          <div className="space-y-1 text-[11px] text-slate-600">
            <label className="flex items-center gap-2">
              <input
                type="radio"
                name={`thinking-${selectedNodeId}`}
                checked={effectiveThinking}
                onChange={() => setThinking(true, current.thinking_effort ?? 'medium')}
              />
              开启
            </label>
            <label className="flex items-center gap-2">
              <input
                type="radio"
                name={`thinking-${selectedNodeId}`}
                checked={!effectiveThinking}
                onChange={() => setThinking(false, null)}
              />
              关闭
            </label>
          </div>
          <Select
            value={current.thinking_effort ?? 'medium'}
            onValueChange={(v) => setThinking(true, v as ThinkingEffort)}
            disabled={!effectiveThinking}
          >
            <SelectTrigger aria-label={`${labels[selectedNodeId]} thinking_effort`} className="w-full text-[11px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {THINKING_EFFORT_OPTIONS.map(o => <SelectItem key={o.value} value={o.value}>{o.label}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5 pt-2 border-t border-[var(--c-border)]">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-[var(--c-text-secondary)]">模型</span>
            <Button
              type="button"
              variant="link"
              onClick={() => setModelRef(null)}
              disabled={current.model_ref === undefined}
              className="h-auto p-0 text-[10px] text-[var(--c-text-muted)] hover:text-[var(--c-text-secondary)] disabled:opacity-30"
            >
              恢复默认
            </Button>
          </div>
          {(() => {
            const allModels = [...(registry?.cloudModels ?? []), ...(registry?.customModels ?? [])]
            return (
              <Combobox
                items={allModels.map(m => m.id)}
                value={current.model_ref ?? null}
                onValueChange={(id) => { if (id) setModelRef(id) }}
                itemToStringLabel={(id) => resolveModelRegistryLabel(registry, id)}
              >
                <ComboboxInput
                  placeholder="跟随全局默认"
                  className="font-mono text-[11px]"
                  aria-label={`${labels[selectedNodeId]}-model-ref`}
                />
                <ComboboxContent>
                  <ComboboxEmpty>无匹配模型</ComboboxEmpty>
                  <ComboboxList>
                    {(id: string) => (
                      <ComboboxItem key={id} value={id}>
                        {resolveModelEntryLabel(allModels.find(m => m.id === id) ?? { id, label: '' })}
                      </ComboboxItem>
                    )}
                  </ComboboxList>
                </ComboboxContent>
              </Combobox>
            )
          })()}
        </div>
        {styleGuardNodeIds.has(selectedNodeId) && (
          <div className="space-y-1.5 pt-2 border-t border-slate-100">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-slate-700">文风守卫</span>
              <Button
                type="button"
                variant="link"
                onClick={() => setStyleGuardDisabled(null)}
                disabled={current.disable_style_guard === undefined}
                className="h-auto p-0 text-[10px] text-slate-400 hover:text-slate-600 disabled:opacity-30"
              >
                恢复默认
              </Button>
            </div>
            <label className="flex items-center gap-2 text-[11px] text-slate-600">
              <Switch
                checked={current.disable_style_guard ?? false}
                onCheckedChange={(v) => setStyleGuardDisabled(v)}
              />
              跳过禁用词/句式守卫
            </label>
          </div>
        )}
        {selectedNodeId === 'derive_char' && (
          <div className="space-y-1.5 pt-2 border-t border-slate-100">
            <div className="flex items-center justify-between">
              <span className="text-xs font-medium text-slate-700">并发推演</span>
              <Button
                type="button"
                variant="link"
                onClick={() => setConcurrent(null)}
                disabled={current.concurrent === undefined}
                className="h-auto p-0 text-[10px] text-slate-400 hover:text-slate-600 disabled:opacity-30"
              >
                恢复默认
              </Button>
            </div>
            <label className="flex items-center gap-2 text-[11px] text-slate-600">
              <Switch
                checked={current.concurrent ?? false}
                onCheckedChange={(v) => setConcurrent(v)}
              />
              并发推演角色状态
            </label>
          </div>
        )}
      </div>
    </div>
  )
}
