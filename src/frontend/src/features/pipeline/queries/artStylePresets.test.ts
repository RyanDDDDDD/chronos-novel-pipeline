// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import { useArtStylePresets } from '@/features/pipeline/queries/artStylePresets'

afterEach(() => {
  vi.unstubAllGlobals()
})

function wrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return React.createElement(QueryClientProvider, { client }, children)
}

describe('useArtStylePresets', () => {
  it('fetches and normalizes the preset list', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true,
      json: async () => ({
        presets: [{ id: 'anime', label: '日系动漫', preview_url: '/art-style-presets/anime.jpg' }],
      }),
    })))

    const { result } = renderHook(() => useArtStylePresets(), { wrapper })

    await waitFor(() => expect(result.current.data).toBeTruthy())
    expect(result.current.data).toEqual([
      { id: 'anime', label: '日系动漫', previewUrl: '/art-style-presets/anime.jpg' },
    ])
  })

  it('returns an empty array when the fetch fails', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new Error('network down') }))

    const { result } = renderHook(() => useArtStylePresets(), { wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual([])
  })
})
