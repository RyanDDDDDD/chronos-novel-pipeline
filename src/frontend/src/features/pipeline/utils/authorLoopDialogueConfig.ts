export type LlmParamNodeId = 'director' | 'review' | 'state_derive'
export type SandboxLlmParamNodeId =
  'prose' | 'derive_char' | 'derive_scene' | 'summary_fold' | 'event_extract' | 'profile_mutate' | 'suggest'
  | 'dialogue_draft' | 'identify_cast' | 'selection_rewrite' | 'scene_image'
export type ImportLlmParamNodeId =
  'image_recognition' | 'text_recognition' | 'review' | 'auto_build_setup' | 'timeline_derive'
  | 'setup_quality_review' | 'skeleton_writer' | 'beat_dialogue_draft' | 'prose_style_extraction'
  | 'incremental_relationship' | 'character_portrait'
export type LlmParamKey = 'temperature' | 'top_p' | 'frequency_penalty' | 'presence_penalty'
export type ThinkingEffort = 'low' | 'medium' | 'high'
export type LlmProvider = 'cloud' | 'local'
export type LlmNodeParams = Partial<Record<LlmParamKey, number>> & {
  enable_thinking?: boolean
  thinking_effort?: ThinkingEffort
  model_ref?: string
  provider?: LlmProvider
  base_url?: string
  model?: string
  disable_style_guard?: boolean
  concurrent?: boolean
}

const LLM_PARAM_NODE_IDS: LlmParamNodeId[] = ['director', 'review', 'state_derive']
const SANDBOX_LLM_PARAM_NODE_IDS: SandboxLlmParamNodeId[] =
  ['prose', 'derive_char', 'derive_scene', 'summary_fold', 'event_extract', 'profile_mutate', 'suggest', 'dialogue_draft', 'identify_cast', 'selection_rewrite', 'scene_image']
const IMPORT_LLM_PARAM_NODE_IDS: ImportLlmParamNodeId[] =
  ['image_recognition', 'text_recognition', 'review', 'auto_build_setup', 'timeline_derive', 'setup_quality_review',
    'skeleton_writer', 'beat_dialogue_draft', 'prose_style_extraction', 'incremental_relationship', 'character_portrait']
const LLM_PARAM_KEYS: LlmParamKey[] = ['temperature', 'top_p', 'frequency_penalty', 'presence_penalty']
const THINKING_EFFORTS: ThinkingEffort[] = ['low', 'medium', 'high']
/** Core creative nodes default thinking ON; all other pipeline nodes default OFF. */
export const DEFAULT_THINKING_ENABLED_NODE_IDS = [
  'director', 'prose', 'chat_identity',
] as const

export function defaultEnableThinkingForNode(nodeId: string): boolean {
  return (DEFAULT_THINKING_ENABLED_NODE_IDS as readonly string[]).includes(nodeId)
}

export interface DialogueConfig {
  target_words: number
  disabled_buildtime_review_hooks: string[]
  disabled_runtime_review_hooks: string[]
  disabled_setup_review_hooks: string[]
  llm_params: Partial<Record<LlmParamNodeId, LlmNodeParams>>
  sandbox_llm_params: Partial<Record<SandboxLlmParamNodeId, LlmNodeParams>>
  import_llm_params: Partial<Record<ImportLlmParamNodeId, LlmNodeParams>>
  auto_build_character_count: number
  auto_build_chapter_count: number
  chat_identity: string
  recall_cooldown_turns: number
  recall_top_k: number
  portrait_style_prompt: string
  portrait_negative_prompt: string
  portrait_style_preset_id: string
}

export interface BuildtimeReviewHookInfo {
  name: string
  display_name: string
  axis: 'stage' | 'transition'
  enabled: boolean
}

export interface RuntimeReviewHookInfo {
  name: string
  display_name: string
  enabled: boolean
}

export interface SetupReviewHookInfo {
  name: string
  display_name: string
  enabled: boolean
}

export interface DialogueConfigState {
  config: DialogueConfig
  default_identity: string
  buildtime_review_hooks: BuildtimeReviewHookInfo[]
  runtime_review_hooks: RuntimeReviewHookInfo[]
  setup_review_hooks: SetupReviewHookInfo[]
}

function toStringArray(v: unknown): string[] {
  return Array.isArray(v) ? v.map(String) : []
}

function toBuildtimeReviewHooks(v: unknown): BuildtimeReviewHookInfo[] {
  if (!Array.isArray(v)) return []
  return v
    .filter((x): x is Record<string, unknown> => typeof x === 'object' && x !== null)
    .map(x => ({
      name: String(x.name ?? ''),
      display_name: String(x.display_name ?? ''),
      axis: x.axis === 'transition' ? 'transition' : 'stage',
      enabled: x.enabled !== false,
    }))
}

function toRuntimeReviewHooks(v: unknown): RuntimeReviewHookInfo[] {
  if (!Array.isArray(v)) return []
  return v
    .filter((x): x is Record<string, unknown> => typeof x === 'object' && x !== null)
    .map(x => ({
      name: String(x.name ?? ''),
      display_name: String(x.display_name ?? ''),
      enabled: x.enabled !== false,
    }))
}

function toSetupReviewHooks(v: unknown): SetupReviewHookInfo[] {
  if (!Array.isArray(v)) return []
  return v
    .filter((x): x is Record<string, unknown> => typeof x === 'object' && x !== null)
    .map(x => ({
      name: String(x.name ?? ''),
      display_name: String(x.display_name ?? ''),
      enabled: x.enabled !== false,
    }))
}

function toNodeParams<T extends string>(v: unknown, nodeIds: T[]): Partial<Record<T, LlmNodeParams>> {
  if (typeof v !== 'object' || v === null) return {}
  const record = v as Record<string, unknown>
  const out: Partial<Record<T, LlmNodeParams>> = {}
  for (const nodeId of nodeIds) {
    const params = record[nodeId]
    if (typeof params !== 'object' || params === null) continue
    const paramsRecord = params as Record<string, unknown>
    const clean: LlmNodeParams = {}
    for (const key of LLM_PARAM_KEYS) {
      const value = paramsRecord[key]
      if (typeof value === 'number' && Number.isFinite(value)) clean[key] = value
    }
    if (typeof paramsRecord.enable_thinking === 'boolean') {
      clean.enable_thinking = paramsRecord.enable_thinking
    }
    if (THINKING_EFFORTS.includes(paramsRecord.thinking_effort as ThinkingEffort)) {
      clean.thinking_effort = paramsRecord.thinking_effort as ThinkingEffort
    }
    const modelRef = paramsRecord.model_ref
    if (typeof modelRef === 'string' && modelRef.trim()) {
      clean.model_ref = modelRef.trim()
    }
    if (paramsRecord.provider === 'local') {
      // Fields persist independently (like enable_thinking/thinking_effort above) so an
      // in-progress edit (provider picked, base_url/model not typed yet) round-trips intact
      // instead of vanishing -- completeness is only required for the override to take effect.
      clean.provider = 'local'
      const baseUrl = paramsRecord.base_url
      if (typeof baseUrl === 'string' && baseUrl.trim()) clean.base_url = baseUrl.trim()
      const model = paramsRecord.model
      if (typeof model === 'string' && model.trim()) clean.model = model.trim()
    }
    if (typeof paramsRecord.disable_style_guard === 'boolean') {
      clean.disable_style_guard = paramsRecord.disable_style_guard
    }
    if (typeof paramsRecord.concurrent === 'boolean') {
      clean.concurrent = paramsRecord.concurrent
    }
    if (Object.keys(clean).length > 0) out[nodeId] = clean
  }
  return out
}

export async function fetchDialogueConfig(novelId: string): Promise<DialogueConfigState> {
  const data = await fetch(
    `/api/author-loop/dialogue-config?novel_id=${encodeURIComponent(novelId)}`,
  ).then(r => r.json())
  return {
    config: {
      target_words: Number(data.config?.target_words ?? 3000),
      disabled_buildtime_review_hooks: toStringArray(data.config?.disabled_buildtime_review_hooks),
      disabled_runtime_review_hooks: toStringArray(data.config?.disabled_runtime_review_hooks),
      disabled_setup_review_hooks: toStringArray(data.config?.disabled_setup_review_hooks),
      llm_params: toNodeParams(data.config?.llm_params, LLM_PARAM_NODE_IDS),
      sandbox_llm_params: toNodeParams(data.config?.sandbox_llm_params, SANDBOX_LLM_PARAM_NODE_IDS),
      import_llm_params: toNodeParams(data.config?.import_llm_params, IMPORT_LLM_PARAM_NODE_IDS),
      auto_build_character_count: Number(data.config?.auto_build_character_count ?? 5),
      auto_build_chapter_count: Number(data.config?.auto_build_chapter_count ?? 3),
      chat_identity: String(data.config?.chat_identity ?? ''),
      recall_cooldown_turns: Number(data.config?.recall_cooldown_turns ?? 10),
      recall_top_k: Number(data.config?.recall_top_k ?? 5),
      portrait_style_prompt: String(data.config?.portrait_style_prompt ?? ''),
      portrait_negative_prompt: String(data.config?.portrait_negative_prompt ?? ''),
      portrait_style_preset_id: String(data.config?.portrait_style_preset_id ?? 'anime'),
    },
    default_identity: String(data.default_identity ?? ''),
    buildtime_review_hooks: toBuildtimeReviewHooks(data.buildtime_review_hooks),
    runtime_review_hooks: toRuntimeReviewHooks(data.runtime_review_hooks),
    setup_review_hooks: toSetupReviewHooks(data.setup_review_hooks),
  }
}

export async function putDialogueConfig(novelId: string, body: {
  dialogue?: Partial<DialogueConfig>
}): Promise<DialogueConfigState> {
  const data = await fetch(
    `/api/author-loop/dialogue-config?novel_id=${encodeURIComponent(novelId)}`,
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    },
  ).then(r => r.json())
  return fetchDialogueConfig(novelId).catch(() => ({
    config: {
      target_words: Number(data.config?.target_words ?? 3000),
      disabled_buildtime_review_hooks: toStringArray(data.config?.disabled_buildtime_review_hooks),
      disabled_runtime_review_hooks: toStringArray(data.config?.disabled_runtime_review_hooks),
      disabled_setup_review_hooks: toStringArray(data.config?.disabled_setup_review_hooks),
      llm_params: toNodeParams(data.config?.llm_params, LLM_PARAM_NODE_IDS),
      sandbox_llm_params: toNodeParams(data.config?.sandbox_llm_params, SANDBOX_LLM_PARAM_NODE_IDS),
      import_llm_params: toNodeParams(data.config?.import_llm_params, IMPORT_LLM_PARAM_NODE_IDS),
      auto_build_character_count: Number(data.config?.auto_build_character_count ?? 5),
      auto_build_chapter_count: Number(data.config?.auto_build_chapter_count ?? 3),
      chat_identity: String(data.config?.chat_identity ?? ''),
      recall_cooldown_turns: Number(data.config?.recall_cooldown_turns ?? 10),
      recall_top_k: Number(data.config?.recall_top_k ?? 5),
      portrait_style_prompt: String(data.config?.portrait_style_prompt ?? ''),
      portrait_negative_prompt: String(data.config?.portrait_negative_prompt ?? ''),
      portrait_style_preset_id: String(data.config?.portrait_style_preset_id ?? 'anime'),
    },
    default_identity: String(data.default_identity ?? ''),
    buildtime_review_hooks: toBuildtimeReviewHooks(data.buildtime_review_hooks),
    runtime_review_hooks: toRuntimeReviewHooks(data.runtime_review_hooks),
    setup_review_hooks: toSetupReviewHooks(data.setup_review_hooks),
  }))
}
