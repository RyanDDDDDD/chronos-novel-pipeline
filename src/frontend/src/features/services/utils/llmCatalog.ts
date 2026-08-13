export interface CloudModelEntry {
  id: string
  label: string
  provider: 'anthropic' | 'openai_compatible'
  base_url?: string
  client_kwargs?: Record<string, unknown>
}

export interface CustomModelEntry {
  id: string
  label: string
  provider: 'anthropic' | 'openai_compatible'
  base_url: string
  model: string
}

/** Display name for catalog/custom entries; mirrors ServiceConfigPage list labels. */
export function resolveModelEntryLabel(
  entry: Pick<CloudModelEntry, 'id' | 'label'> & Partial<Pick<CustomModelEntry, 'model'>>,
): string {
  const label = entry.label?.trim()
  if (label) return label
  const model = entry.model?.trim()
  if (model) return model
  return entry.id
}

export function resolveModelRegistryLabel(
  registry: { cloudModels: CloudModelEntry[]; customModels: CustomModelEntry[] } | undefined,
  modelRef: string | null | undefined,
): string {
  if (!modelRef) return ''
  const hit = [...(registry?.cloudModels ?? []), ...(registry?.customModels ?? [])]
    .find(m => m.id === modelRef)
  return hit ? resolveModelEntryLabel(hit) : modelRef
}

export async function fetchModelRegistry(): Promise<{ cloudModels: CloudModelEntry[]; customModels: CustomModelEntry[] }> {
  try {
    const res = await fetch('/api/llm/catalog')
    const body = await res.json().catch(() => ({}))
    return {
      cloudModels: Array.isArray(body.cloud_models) ? body.cloud_models : [],
      customModels: Array.isArray(body.custom_models) ? body.custom_models : [],
    }
  } catch {
    return { cloudModels: [], customModels: [] }
  }
}

export async function fetchModelCatalog(): Promise<CloudModelEntry[]> {
  try {
    const res = await fetch('/api/llm/catalog')
    const body = await res.json().catch(() => ({}))
    return Array.isArray(body.cloud_models) ? body.cloud_models : []
  } catch {
    return []
  }
}

export async function fetchLocalModels(localBaseUrl: string): Promise<{ models: string[]; error?: string }> {
  try {
    const res = await fetch(`/api/llm/local-models?base_url=${encodeURIComponent(localBaseUrl)}`)
    const body = await res.json().catch(() => ({}))
    return {
      models: Array.isArray(body.models) ? body.models : [],
      error: typeof body.error === 'string' ? body.error : undefined,
    }
  } catch {
    return { models: [], error: '无法连接后端' }
  }
}

export async function fetchCompatibleModels(
  baseUrl: string,
  apiKey: string,
): Promise<{ models: string[]; error?: string }> {
  try {
    const res = await fetch('/api/llm/compatible-models', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ base_url: baseUrl, api_key: apiKey }),
    })
    const body = await res.json().catch(() => ({}))
    return {
      models: Array.isArray(body.models) ? body.models : [],
      error: typeof body.error === 'string' ? body.error : undefined,
    }
  } catch {
    return { models: [], error: '无法连接后端' }
  }
}

export async function fetchImageGenModelRegistry(): Promise<{
  customModels: { id: string; label: string; model: string }[]
}> {
  try {
    const res = await fetch('/api/image-gen/catalog')
    const body = await res.json()
    return { customModels: Array.isArray(body.custom_models) ? body.custom_models : [] }
  } catch {
    return { customModels: [] }
  }
}

export async function fetchNovitaModelCatalog(): Promise<{ models: string[]; baseModels: Record<string, string> }> {
  try {
    const res = await fetch('/api/image-gen/novita-models')
    const body = await res.json()
    return {
      models: Array.isArray(body.models) ? body.models : [],
      baseModels: body.base_models && typeof body.base_models === 'object' ? body.base_models : {},
    }
  } catch {
    return { models: [], baseModels: {} }
  }
}

export async function fetchArtStylePresets(): Promise<{ id: string; label: string; previewUrl: string }[]> {
  try {
    const res = await fetch('/api/image-gen/style-presets')
    const body = await res.json()
    const presets = Array.isArray(body.presets) ? body.presets : []
    return presets.map((p: { id: string; label: string; preview_url: string }) => ({
      id: p.id, label: p.label, previewUrl: p.preview_url,
    }))
  } catch {
    return []
  }
}
