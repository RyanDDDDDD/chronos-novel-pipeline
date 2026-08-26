type ApiResp<T> = { ok?: boolean; error?: string } & T

export type NovelImportConfig = {
  chunk_size?: number
  concurrency?: number | null
  warn_threshold_chars?: number
  compaction_interval?: number
}

export type NovelsConfig = {
  trash_retention_days?: number
}

export type ChronosConfig = {
  llm?: {
    cloud_model_id?: string
    /** Dedicated model for style_guard sentence rewrites; empty = cloud default. */
    style_guard_model_ref?: string
    custom_models?: {
      id: string
      label: string
      provider: 'anthropic' | 'openai_compatible' | 'image_gen'
      base_url: string
      model: string
      api_key?: string
      client_kwargs?: Record<string, unknown>
    }[]
    local_base_url?: string
    local_model?: string
    max_tokens?: number
    local_preset?: string
    temperature?: number
    top_p?: number
    top_k?: number
    repetition_penalty?: number
    repeat_last_n?: number
    min_p?: number
  }
  api?: {
    model_api_keys?: Record<string, string>
    tavily_api_key?: string
    qianfan_api_key?: string
    search_provider?: 'tavily' | 'baidu_qianfan' | 'chronos_cloud'
    search_top_k?: number
    cloud_auth_base_url?: string
    cloud_search_base_url?: string
  }
  novel_import?: NovelImportConfig
  novels?: NovelsConfig
}

export const NOVEL_IMPORT_DEFAULTS: Required<Omit<NovelImportConfig, 'concurrency'>> & {
  concurrency: number | null
} = {
  chunk_size: 10000,
  concurrency: null,
  warn_threshold_chars: 100000,
  compaction_interval: 5,
}

export const NOVELS_DEFAULTS: Required<NovelsConfig> = {
  trash_retention_days: 30,
}

export function clampInt(v: string, fallback: number): number {
  const n = Number.parseInt(v, 10)
  return Number.isFinite(n) ? n : fallback
}

export async function fetchChronosConfig(): Promise<ChronosConfig> {
  const res = await fetch('/api/config')
  const body = (await res.json().catch(() => ({}))) as ApiResp<{ config?: ChronosConfig }>
  if (!res.ok) throw new Error(body.error ?? `读取失败 (HTTP ${res.status})`)
  return body.config ?? {}
}

export async function saveChronosConfig(cfg: ChronosConfig): Promise<ChronosConfig> {
  const res = await fetch('/api/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ config: cfg }),
  })
  const body = (await res.json().catch(() => ({}))) as ApiResp<{ config?: ChronosConfig }>
  if (!res.ok || body.ok === false) throw new Error(body.error ?? `保存失败 (HTTP ${res.status})`)
  return body.config ?? {}
}

export function resolveNovelImport(cfg: ChronosConfig | undefined): typeof NOVEL_IMPORT_DEFAULTS {
  const raw = cfg?.novel_import ?? {}
  return {
    chunk_size: raw.chunk_size ?? NOVEL_IMPORT_DEFAULTS.chunk_size,
    concurrency: raw.concurrency ?? NOVEL_IMPORT_DEFAULTS.concurrency,
    warn_threshold_chars: raw.warn_threshold_chars ?? NOVEL_IMPORT_DEFAULTS.warn_threshold_chars,
    compaction_interval: raw.compaction_interval ?? NOVEL_IMPORT_DEFAULTS.compaction_interval,
  }
}

export function resolveNovelsConfig(cfg: ChronosConfig | undefined): typeof NOVELS_DEFAULTS {
  const raw = cfg?.novels ?? {}
  return {
    trash_retention_days: raw.trash_retention_days ?? NOVELS_DEFAULTS.trash_retention_days,
  }
}
