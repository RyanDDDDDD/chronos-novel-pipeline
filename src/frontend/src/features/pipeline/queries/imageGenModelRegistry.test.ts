/** @vitest-environment jsdom */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import { useImageGenModelRegistry } from '@/features/pipeline/queries/modelRegistry'

afterEach(() => {
  vi.restoreAllMocks()
})

describe('useImageGenModelRegistry', () => {
  it('fetches the image-gen model registry', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      json: () => Promise.resolve({ custom_models: [{ id: 'img-1', label: '我的Novita', model: 'flux-1' }] }),
    }))
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const { result } = renderHook(() => useImageGenModelRegistry(), {
      wrapper: ({ children }) => React.createElement(QueryClientProvider, { client: qc }, children),
    })
    await waitFor(() => expect(result.current.data?.customModels).toEqual([
      { id: 'img-1', label: '我的Novita', model: 'flux-1' },
    ]))
  })
})
