/** @vitest-environment jsdom */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import { useModelRegistry } from '@/features/pipeline/queries/modelRegistry'

vi.mock('@/features/services/utils/llmCatalog', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/features/services/utils/llmCatalog')>()
  return {
    ...actual,
    fetchModelRegistry: vi.fn(async () => ({
      cloudModels: [{ id: 'claude-opus-4-7', label: 'Claude Opus 4.7', provider: 'anthropic' }],
      customModels: [{ id: 'custom-1', label: '我的模型', provider: 'openai_compatible', base_url: 'https://x.example.com/v1', model: 'm1' }],
    })),
  }
})

afterEach(() => {
  vi.restoreAllMocks()
})

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return React.createElement(QueryClientProvider, { client: qc }, children)
}

describe('useModelRegistry', () => {
  it('返回合并后的 cloud + custom 模型', async () => {
    const { result } = renderHook(() => useModelRegistry(), { wrapper })
    await waitFor(() => expect(result.current.data).toBeDefined())
    expect(result.current.data?.cloudModels).toHaveLength(1)
    expect(result.current.data?.customModels).toHaveLength(1)
  })
})
