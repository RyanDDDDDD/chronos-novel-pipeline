import { describe, it, expect, vi, afterEach } from 'vitest'
import { fetchModelRegistry, resolveModelEntryLabel, resolveModelRegistryLabel } from '@/features/services/utils/llmCatalog'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('fetchModelRegistry', () => {
  it('合并 cloud_models 与 custom_models', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      json: async () => ({
        cloud_models: [{ id: 'claude-opus-4-7', label: 'Claude Opus 4.7', provider: 'anthropic' }],
        custom_models: [{ id: 'custom-1', label: '我的模型', provider: 'openai_compatible', base_url: 'https://x.example.com/v1', model: 'm1' }],
      }),
    })))
    const result = await fetchModelRegistry()
    expect(result.cloudModels).toEqual([{ id: 'claude-opus-4-7', label: 'Claude Opus 4.7', provider: 'anthropic' }])
    expect(result.customModels).toEqual([{ id: 'custom-1', label: '我的模型', provider: 'openai_compatible', base_url: 'https://x.example.com/v1', model: 'm1' }])
  })

  it('请求失败时返回空列表', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('network down') }))
    const result = await fetchModelRegistry()
    expect(result).toEqual({ cloudModels: [], customModels: [] })
  })

  it('响应体缺字段时兜底空数组', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({}) })))
    const result = await fetchModelRegistry()
    expect(result).toEqual({ cloudModels: [], customModels: [] })
  })
})

describe('resolveModelEntryLabel', () => {
  it('优先 label，空 label 回退 model，再回退 id', () => {
    expect(resolveModelEntryLabel({ id: 'custom-1', label: '显示名', model: 'm1' })).toBe('显示名')
    expect(resolveModelEntryLabel({ id: 'custom-1', label: '  ', model: 'm1' })).toBe('m1')
    expect(resolveModelEntryLabel({ id: 'custom-1', label: '', model: '' })).toBe('custom-1')
  })
})

describe('resolveModelRegistryLabel', () => {
  const registry = {
    cloudModels: [{ id: 'cloud-1', label: 'Cloud', provider: 'anthropic' as const }],
    customModels: [{
      id: 'custom-1', label: '', provider: 'openai_compatible' as const,
      base_url: 'https://x.example.com/v1', model: 'my-model',
    }],
  }

  it('按 model_ref 查表并解析显示名', () => {
    expect(resolveModelRegistryLabel(registry, 'custom-1')).toBe('my-model')
    expect(resolveModelRegistryLabel(registry, 'cloud-1')).toBe('Cloud')
    expect(resolveModelRegistryLabel(registry, 'missing')).toBe('missing')
  })
})
