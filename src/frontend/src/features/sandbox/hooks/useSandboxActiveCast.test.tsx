/** @vitest-environment jsdom */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import React from 'react'
import { Provider } from 'react-redux'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { buildTestStore } from '@/test/renderWithClient'
import { useSandboxActiveCast } from '@/features/sandbox/hooks/useSandboxActiveCast'
import { wsEventReceived } from '@/shared/store/wsActions'
import { sandboxChatReset } from '@/features/sandbox/store/sandboxSlice'

function mockSandboxHistory(activeCast: string[] = []) {
  vi.spyOn(global, 'fetch').mockImplementation(async (url) => {
    if (String(url).includes('/api/story-sandbox/history')) {
      return {
        ok: true,
        json: async () => ({ rounds: [], active_cast: activeCast }),
      } as Response
    }
    return { ok: true, json: async () => ({}) } as Response
  })
}

function renderActiveCastHook(novelId: string, chapter: number, branchId = 'b1') {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  })
  const store = buildTestStore({ connection: { connected: true } })
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <Provider store={store}>
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </Provider>
  )
  return { ...renderHook(() => useSandboxActiveCast(novelId, chapter, branchId), { wrapper }), store }
}

describe('useSandboxActiveCast', () => {
  beforeEach(() => {
    mockSandboxHistory(['甲', '乙'])
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('seeds from history active_cast once loaded', async () => {
    const { result } = renderActiveCastHook('novel-a', 1)
    expect(result.current).toEqual([])
    await waitFor(() => expect(result.current).toEqual(['甲', '乙']))
  })

  it('updates on story_sandbox_final WS message', async () => {
    const { result, store } = renderActiveCastHook('novel-a', 1)
    await waitFor(() => expect(result.current).toEqual(['甲', '乙']))
    act(() => { store.dispatch(wsEventReceived({ type: 'story_sandbox_final', content: '正文', active_cast: ['丙'] })) })
    expect(result.current).toEqual(['丙'])
  })

  it('updates on story_sandbox_states WS message (derive_char-corrected roster, incl. mid-scene entrants)', async () => {
    const { result, store } = renderActiveCastHook('novel-a', 1)
    await waitFor(() => expect(result.current).toEqual(['甲', '乙']))
    // story_sandbox_final's active_cast is a pre-derivation keyword-scan estimate that can miss
    // a character who first appears in this round's not-yet-written prose; story_sandbox_states
    // carries the corrected roster from derive_char and must override it.
    act(() => { store.dispatch(wsEventReceived({ type: 'story_sandbox_final', content: '正文', active_cast: ['甲'] })) })
    expect(result.current).toEqual(['甲'])
    act(() => {
      store.dispatch(wsEventReceived({
        type: 'story_sandbox_states', states: {}, scene_state: {}, active_cast: ['甲', '丙'],
      }))
    })
    expect(result.current).toEqual(['甲', '丙'])
  })

  it('updates on story_sandbox_rewrite_done WS message', async () => {
    const { result, store } = renderActiveCastHook('novel-a', 1)
    await waitFor(() => expect(result.current).toEqual(['甲', '乙']))
    act(() => {
      store.dispatch(wsEventReceived({
        type: 'story_sandbox_rewrite_done', content: '新正文', active_cast: ['乙', '丁'],
      }))
    })
    expect(result.current).toEqual(['乙', '丁'])
  })

  it('clears cast when the conversation is reset (e.g. on branch delete)', async () => {
    // Mirrors StorySandboxPanel's handleDeleteBranch -- dispatching sandboxChatReset directly
    // rather than the old react-query invalidation + refetch-empty dance, since this hook no
    // longer owns any query of its own.
    const { result, store } = renderActiveCastHook('novel-a', 1)
    await waitFor(() => expect(result.current).toEqual(['甲', '乙']))
    act(() => { store.dispatch(sandboxChatReset()) })
    expect(result.current).toEqual([])
  })

  it('resets to new scope history on novelId/chapter switch', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation(async (url) => {
      const u = String(url)
      if (u.includes('novel-a') && u.includes('chapter=1')) {
        return { ok: true, json: async () => ({ rounds: [], active_cast: ['甲'] }) } as Response
      }
      if (u.includes('novel-b') && u.includes('chapter=2')) {
        return { ok: true, json: async () => ({ rounds: [], active_cast: ['乙'] }) } as Response
      }
      return { ok: true, json: async () => ({ rounds: [], active_cast: [] }) } as Response
    })
    const { result, rerender } = renderHook(
      ({ novelId, chapter, branchId }) => useSandboxActiveCast(novelId, chapter, branchId),
      {
        initialProps: { novelId: 'novel-a', chapter: 1, branchId: 'b1' },
        wrapper: ({ children }) => {
          const client = new QueryClient({
            defaultOptions: { queries: { retry: false, staleTime: Infinity } },
          })
          const store = buildTestStore({ connection: { connected: true } })
          return (
            <Provider store={store}>
              <QueryClientProvider client={client}>{children}</QueryClientProvider>
            </Provider>
          )
        },
      },
    )
    await waitFor(() => expect(result.current).toEqual(['甲']))
    rerender({ novelId: 'novel-b', chapter: 2, branchId: 'b1' })
    await waitFor(() => expect(result.current).toEqual(['乙']))
    expect(fetchSpy.mock.calls.some(([url]) => String(url).includes('novel-b'))).toBe(true)
  })
})
