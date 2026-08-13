import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'
import { useSandboxCastArchives, useSandboxRelatedCastArchives, useSandboxMemoryArchive } from './storySandbox'

function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
}

beforeEach(() => { vi.stubGlobal('fetch', vi.fn()) })
afterEach(() => { vi.unstubAllGlobals() })

describe('useSandboxCastArchives', () => {
  it('does not fetch when novelId is empty', () => {
    const { result } = renderHook(() => useSandboxCastArchives('', 0, ['甲']), { wrapper: wrapper() })
    expect(result.current.fetchStatus).toBe('idle')
  })

  it('is enabled when chapter is 0 (free mode)', async () => {
    vi.mocked(fetch).mockResolvedValue({
      json: async () => ({ characters: [] }),
    } as Response)
    const { result } = renderHook(() => useSandboxCastArchives('novel-1', 0, ['甲']), { wrapper: wrapper() })
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    const url = String(vi.mocked(fetch).mock.calls[0]?.[0])
    expect(new URL(url, 'http://localhost').searchParams.get('names')).toBe('甲')
  })

  it('refetches when names change (different sorted join → different query key)', async () => {
    vi.mocked(fetch).mockResolvedValue({
      json: async () => ({ characters: [] }),
    } as Response)
    const { result, rerender } = renderHook(
      ({ names }: { names: string[] }) => useSandboxCastArchives('novel-1', 3, names),
      { wrapper: wrapper(), initialProps: { names: ['bob', 'alice'] } },
    )
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(fetch).toHaveBeenCalledTimes(1)
    const firstUrl = String(vi.mocked(fetch).mock.calls[0]?.[0])
    expect(new URL(firstUrl, 'http://localhost').searchParams.get('names')).toBe('alice,bob')

    rerender({ names: ['bob', 'alice', 'carol'] })
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2))
    const secondUrl = String(vi.mocked(fetch).mock.calls[1]?.[0])
    expect(new URL(secondUrl, 'http://localhost').searchParams.get('names')).toBe('alice,bob,carol')
  })

  it('does not refetch when names are reordered (sorted join is stable)', async () => {
    vi.mocked(fetch).mockResolvedValue({
      json: async () => ({ characters: [] }),
    } as Response)
    const { result, rerender } = renderHook(
      ({ names }: { names: string[] }) => useSandboxCastArchives('novel-1', 3, names),
      { wrapper: wrapper(), initialProps: { names: ['bob', 'alice'] } },
    )
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(fetch).toHaveBeenCalledTimes(1)

    rerender({ names: ['alice', 'bob'] })
    await waitFor(() => expect(result.current.isFetching).toBe(false))
    expect(fetch).toHaveBeenCalledTimes(1)
  })
})

describe('useSandboxRelatedCastArchives', () => {
  it('does not fetch when novelId is empty', () => {
    const { result } = renderHook(
      () => useSandboxRelatedCastArchives('', 0, ['甲']), { wrapper: wrapper() },
    )
    expect(result.current.fetchStatus).toBe('idle')
  })

  it('requests the related-cast-archives endpoint with present names', async () => {
    vi.mocked(fetch).mockResolvedValue({ json: async () => ({ characters: [] }) } as Response)
    const { result } = renderHook(
      () => useSandboxRelatedCastArchives('novel-1', 3, ['乙', '甲']), { wrapper: wrapper() },
    )
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    const url = String(vi.mocked(fetch).mock.calls[0]?.[0])
    const parsed = new URL(url, 'http://localhost')
    expect(parsed.pathname).toBe('/api/story-sandbox/related-cast-archives')
    expect(parsed.searchParams.get('present')).toBe('乙,甲')
    expect(parsed.searchParams.get('chapter')).toBe('3')
    expect(parsed.searchParams.get('novel_id')).toBe('novel-1')
  })

  it('refetches when present names change (different sorted join → different query key)', async () => {
    vi.mocked(fetch).mockResolvedValue({ json: async () => ({ characters: [] }) } as Response)
    const { result, rerender } = renderHook(
      ({ present }: { present: string[] }) => useSandboxRelatedCastArchives('novel-1', 3, present),
      { wrapper: wrapper(), initialProps: { present: ['甲'] } },
    )
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(fetch).toHaveBeenCalledTimes(1)

    rerender({ present: ['甲', '乙'] })
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2))
  })
})

describe('useSandboxMemoryArchive', () => {
  it('does not fetch when novelId is empty', () => {
    const { result } = renderHook(
      () => useSandboxMemoryArchive('', 1, 'b1'), { wrapper: wrapper() },
    )
    expect(result.current.fetchStatus).toBe('idle')
  })

  it('requests chapter and branch_id as query params', async () => {
    vi.mocked(fetch).mockResolvedValue({ json: async () => ({ entries: [] }) } as Response)
    const { result } = renderHook(
      () => useSandboxMemoryArchive('novel-1', 5, 'b1'), { wrapper: wrapper() },
    )
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    const url = String(vi.mocked(fetch).mock.calls[0]?.[0])
    const parsed = new URL(url, 'http://localhost')
    expect(parsed.searchParams.get('chapter')).toBe('5')
    expect(parsed.searchParams.get('branch_id')).toBe('b1')
  })

  it('omits branch_id query param when branchId is null', async () => {
    vi.mocked(fetch).mockResolvedValue({ json: async () => ({ entries: [] }) } as Response)
    const { result } = renderHook(
      () => useSandboxMemoryArchive('novel-1', 5, null), { wrapper: wrapper() },
    )
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    const url = String(vi.mocked(fetch).mock.calls[0]?.[0])
    expect(new URL(url, 'http://localhost').searchParams.has('branch_id')).toBe(false)
  })

  it('parses entries into camelCase SandboxMemoryEntry shape', async () => {
    vi.mocked(fetch).mockResolvedValue({
      json: async () => ({
        entries: [{
          id: 'e1', chapter: 3, turn_index: 2, time: '子夜', location: '藏经阁',
          characters: ['甲'], summary: '摘要', entities: ['玉佩'], branch_id: 'b1',
        }],
      }),
    } as Response)
    const { result } = renderHook(
      () => useSandboxMemoryArchive('novel-1', 5, 'b1'), { wrapper: wrapper() },
    )
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(result.current.data).toEqual([{
      id: 'e1', chapter: 3, turnIndex: 2, time: '子夜', location: '藏经阁',
      characters: ['甲'], summary: '摘要', entities: ['玉佩'], branchId: 'b1',
    }])
  })

  it('refetches when branchId changes (different query key)', async () => {
    vi.mocked(fetch).mockResolvedValue({ json: async () => ({ entries: [] }) } as Response)
    const { result, rerender } = renderHook(
      ({ branchId }: { branchId: string | null }) => useSandboxMemoryArchive('novel-1', 5, branchId),
      { wrapper: wrapper(), initialProps: { branchId: 'b1' as string | null } },
    )
    await waitFor(() => expect(result.current.isSuccess).toBe(true))
    expect(fetch).toHaveBeenCalledTimes(1)
    rerender({ branchId: 'b2' })
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2))
  })
})
