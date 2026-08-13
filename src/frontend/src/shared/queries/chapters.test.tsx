import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import { useChapters, useChapterNumbers } from './chapters'

function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
}

beforeEach(() => { vi.stubGlobal('fetch', vi.fn()) })
afterEach(() => { vi.unstubAllGlobals() })

describe('useChapters', () => {
  it('novelId 为空时不查', () => {
    const { result } = renderHook(() => useChapters(''), { wrapper: wrapper() })
    expect(result.current.fetchStatus).toBe('idle')
  })

  it('拉取并过滤非法章号', async () => {
    vi.mocked(fetch).mockResolvedValue({
      json: async () => ({ chapters: [{ chapter: 1 }, { chapter: 0 }, { chapter: 2 }] }),
    } as Response)
    const { result } = renderHook(() => useChapters('n1'), { wrapper: wrapper() })
    await waitFor(() => expect(result.current.data).toEqual([{ chapter: 1 }, { chapter: 2 }]))
  })
})

describe('useChapterNumbers', () => {
  it('unions the current chapter with fetched chapters, deduped and sorted', async () => {
    vi.mocked(fetch).mockResolvedValue({
      json: async () => ({ chapters: [{ chapter: 3, title: null }, { chapter: 1, title: null }] }),
    } as Response)
    const { result } = renderHook(() => useChapterNumbers('n1', 5), { wrapper: wrapper() })
    await waitFor(() => expect(result.current).toEqual([1, 3, 5]))
  })
})
