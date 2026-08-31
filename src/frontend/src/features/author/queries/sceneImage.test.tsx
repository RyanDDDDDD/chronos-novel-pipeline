import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import { useAuthorSceneImages, requestAuthorSceneImage } from './sceneImage'

function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
}

beforeEach(() => { vi.stubGlobal('fetch', vi.fn()) })
afterEach(() => { vi.unstubAllGlobals() })

describe('useAuthorSceneImages', () => {
  it('GETs the chapter-scoped endpoint and returns the stage-index → url map', async () => {
    vi.mocked(fetch).mockResolvedValue({
      json: async () => ({ images: { '0': '/api/author-loop/scene-image/6/0/file?v=a.png' } }),
    } as Response)
    const { result } = renderHook(() => useAuthorSceneImages('n1', 6), { wrapper: wrapper() })
    await waitFor(() => expect(result.current.data).toEqual({
      '0': '/api/author-loop/scene-image/6/0/file?v=a.png',
    }))
    expect(fetch).toHaveBeenCalledWith('/api/author-loop/scene-images?chapter=6')
  })

  it('falls back to an empty map when the body has no usable images field', async () => {
    vi.mocked(fetch).mockResolvedValue({ json: async () => ({ images: null }) } as Response)
    const { result } = renderHook(() => useAuthorSceneImages('n1', 6), { wrapper: wrapper() })
    await waitFor(() => expect(result.current.data).toEqual({}))
  })

  it('falls back to an empty map when the response body is not JSON', async () => {
    vi.mocked(fetch).mockResolvedValue({
      json: async () => { throw new Error('not json') },
    } as unknown as Response)
    const { result } = renderHook(() => useAuthorSceneImages('n1', 6), { wrapper: wrapper() })
    await waitFor(() => expect(result.current.data).toEqual({}))
  })

  it('stays idle for a chapter below 1 (no chapter selected yet)', () => {
    const { result } = renderHook(() => useAuthorSceneImages('n1', 0), { wrapper: wrapper() })
    expect(result.current.fetchStatus).toBe('idle')
    expect(fetch).not.toHaveBeenCalled()
  })
})

describe('requestAuthorSceneImage', () => {
  it('POSTs chapter + index as JSON and returns the parsed body', async () => {
    vi.mocked(fetch).mockResolvedValue({ json: async () => ({ ok: true }) } as Response)
    await expect(requestAuthorSceneImage(6, 2)).resolves.toEqual({ ok: true })
    expect(fetch).toHaveBeenCalledWith('/api/author-loop/scene-image', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chapter: 6, index: 2 }),
    })
  })

  it('reports not-ok when the body is unparseable', async () => {
    vi.mocked(fetch).mockResolvedValue({
      json: async () => { throw new Error('not json') },
    } as unknown as Response)
    await expect(requestAuthorSceneImage(6, 2)).resolves.toEqual({ ok: false })
  })

  it('reports not-ok when the request itself throws', async () => {
    vi.mocked(fetch).mockRejectedValue(new Error('offline'))
    await expect(requestAuthorSceneImage(6, 2)).resolves.toEqual({ ok: false })
  })
})
