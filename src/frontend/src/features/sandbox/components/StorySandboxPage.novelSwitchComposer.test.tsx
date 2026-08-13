/** @vitest-environment jsdom */
import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Provider } from 'react-redux'
import { buildTestStore } from '@/test/renderWithClient'
import StorySandboxPage from '@/features/sandbox/components/StorySandboxPage'
import type { Novel } from '@/shared/utils/novels'

// Real StorySandboxPanel (NOT mocked) -- this test exists specifically to catch bugs the
// mocked-panel StorySandboxPage.test.tsx and the directly-prop-driven StorySandboxPanel.test.tsx
// can't see: whether the REAL parent chain (StorySandboxPage deriving novelId/chapter/branchId
// from useActiveNovelId() + Redux + React Query) actually delivers a correct, settled prop set
// to the composer after a real novel switch, not just whether the panel behaves correctly when
// handed already-correct props directly.

const useSandboxActiveCastMock = vi.hoisted(() => vi.fn(() => []))
const useCastMock = vi.hoisted(() => vi.fn(() => ({ data: [] })))
const useWorldMock = vi.hoisted(() => vi.fn(() => ({ data: undefined })))

vi.mock('@/shared/queries/setup', () => ({
  useCast: () => useCastMock(),
  useWorld: () => useWorldMock(),
}))
vi.mock('@/features/sandbox/hooks/useSandboxActiveCast', () => ({
  useSandboxActiveCast: (...args: unknown[]) => useSandboxActiveCastMock(...args),
}))
vi.mock('@/features/sandbox/hooks/useStorySandbox', () => ({
  useStorySandbox: () => ({
    sendMessage: vi.fn(), stopTurn: vi.fn(), regenerateSuggestions: vi.fn(),
    startRewrite: vi.fn(), rewriteSelection: vi.fn(),
  }),
}))
vi.mock('@/features/sandbox/components/SandboxCharacterPanel', () => ({
  default: () => <aside data-testid="cast-panel" />,
}))

function mockFetch() {
  vi.spyOn(global, 'fetch').mockImplementation(async (url) => {
    const u = String(url)
    if (u.includes('/api/chapters')) {
      return { ok: true, json: async () => ({ chapters: [{ chapter: 1, title: null }] }) } as Response
    }
    if (u.includes('/api/story-sandbox/branches')) {
      const branches = u.includes('novel_id=novel-A')
        ? [{ id: 'a1', chapter: 1, name: 'A线', created_at: 't', updated_at: 't' }]
        : [{ id: 'b1', chapter: 1, name: 'B线', created_at: 't', updated_at: 't' }]
      return { ok: true, json: async () => ({ branches }) } as Response
    }
    if (u.includes('/api/story-sandbox/history')) {
      return { ok: true, json: async () => ({ rounds: [], active_cast: [], live_round: null }) } as Response
    }
    return { ok: true, json: async () => ({}) } as Response
  })
}

function mockLocalStorage() {
  const store = new Map<string, string>()
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
    setItem: (k: string, v: string) => { store.set(k, v) },
    removeItem: (k: string) => { store.delete(k) },
    clear: () => { store.clear() },
  })
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
  client.setQueryData<Novel[]>(['novels'], [
    { id: 'novel-A', name: 'A', active: true },
    { id: 'novel-B', name: 'B', active: false },
  ])
  const store = buildTestStore({ ui: { chapter: 1 } } as never)
  const setActive = (id: string) => {
    client.setQueryData<Novel[]>(['novels'], (old) => (
      old?.map((n) => ({ ...n, active: n.id === id })) ?? old
    ))
  }
  const { rerender } = render(
    <Provider store={store}>
      <QueryClientProvider client={client}>
        <StorySandboxPage />
      </QueryClientProvider>
    </Provider>,
  )
  return { setActive, rerender: () => rerender(
    <Provider store={store}>
      <QueryClientProvider client={client}>
        <StorySandboxPage />
      </QueryClientProvider>
    </Provider>,
  ) }
}

describe('StorySandboxPage real composer across a real novel switch', () => {
  beforeEach(() => {
    mockFetch()
    mockLocalStorage()
    sessionStorage.clear()
    localStorage.setItem('story-sandbox-mode:novel-A', 'chapter')
    localStorage.setItem('story-sandbox-mode:novel-B', 'chapter')
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('clears the composer (and does not leak text into the other novel) across a real active-novel switch', async () => {
    const { setActive, rerender } = renderPage()

    await waitFor(() => expect(screen.getByPlaceholderText(/给导演指令/)).toBeTruthy())
    fireEvent.change(screen.getByPlaceholderText(/给导演指令/), { target: { value: 'A的草稿' } })
    await waitFor(() => expect(sessionStorage.getItem('story-sandbox-draft:novel-A:1')).toBe('A的草稿'))

    setActive('novel-B')
    rerender()

    await waitFor(() => {
      expect(screen.getByPlaceholderText(/给导演指令/)).toHaveProperty('value', '')
    }, { timeout: 3000 })
  })

  it('restores novel A\'s own draft when switching back to it', async () => {
    const { setActive, rerender } = renderPage()

    await waitFor(() => expect(screen.getByPlaceholderText(/给导演指令/)).toBeTruthy())
    fireEvent.change(screen.getByPlaceholderText(/给导演指令/), { target: { value: 'A的草稿' } })
    await waitFor(() => expect(sessionStorage.getItem('story-sandbox-draft:novel-A:1')).toBe('A的草稿'))

    setActive('novel-B')
    rerender()
    await waitFor(() => expect(screen.getByPlaceholderText(/给导演指令/)).toHaveProperty('value', ''))

    setActive('novel-A')
    rerender()
    await waitFor(() => {
      expect(screen.getByPlaceholderText(/给导演指令/)).toHaveProperty('value', 'A的草稿')
    }, { timeout: 3000 })
    expect(sessionStorage.getItem('story-sandbox-draft:novel-A:1')).toBe('A的草稿')
  })
})
