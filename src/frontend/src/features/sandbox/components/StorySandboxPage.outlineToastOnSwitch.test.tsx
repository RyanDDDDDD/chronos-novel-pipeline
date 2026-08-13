/** @vitest-environment jsdom */
import React from 'react'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { cleanup, render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Provider } from 'react-redux'
import { buildTestStore } from '@/test/renderWithClient'
import { resetSandbox } from '@/features/sandbox/store/sandboxSlice'
import StorySandboxPage from '@/features/sandbox/components/StorySandboxPage'
import type { Novel } from '@/shared/utils/novels'

// Real StorySandboxPanel (NOT mocked) -- reproduces the stage1-outline toast firing on switch
// even when the target novel's sandbox already has content, because the injection effect's
// `isSyncing` guard (sandboxSlice.hydrating) reads `false` in a real transient window:
// resetSandbox() (dispatched synchronously by App.tsx's switch effect) sets hydrating=false as
// its baseline, and nothing sets it back to true until hydrateSandboxChat's own
// sandboxChatHydrateBegin dispatch lands a moment later -- a real gap, not a test artifact.

const useSandboxActiveCastMock = vi.hoisted(() => vi.fn(() => []))
const useCastMock = vi.hoisted(() => vi.fn(() => ({ data: [] })))
const useWorldMock = vi.hoisted(() => vi.fn(() => ({ data: undefined })))
const toastSuccessMock = vi.hoisted(() => vi.fn())

vi.mock('@/shared/queries/setup', () => ({
  useCast: () => useCastMock(),
  useWorld: () => useWorldMock(),
  useSetupSkills: () => ({ data: [] }),
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
vi.mock('@/shared/hooks/useToast', () => ({
  useToast: () => ({
    success: toastSuccessMock, error: vi.fn(), confirm: vi.fn(), prompt: vi.fn(),
    toasts: [], dismiss: vi.fn(),
  }),
}))

let resolveHistory: ((v: unknown) => void) | null = null

function mockFetch() {
  vi.spyOn(global, 'fetch').mockImplementation(async (url) => {
    const u = String(url)
    if (u.includes('/api/chapters')) {
      return { ok: true, json: async () => ({ chapters: [{ chapter: 1, title: null }] }) } as Response
    }
    if (u.includes('/api/story-sandbox/branches')) {
      return {
        ok: true,
        json: async () => ({ branches: [{ id: 'a1', chapter: 1, name: 'A线', created_at: 't', updated_at: 't' }] }),
      } as Response
    }
    if (u.includes('/api/setup/skeleton/')) {
      return {
        ok: true,
        json: async () => ({
          exists: true,
          stages: [{ stage_num: 1, description: '甲乙在书房对峙', location: '书房' }],
        }),
      } as Response
    }
    if (u.includes('/api/story-sandbox/history')) {
      return new Promise((resolve) => { resolveHistory = () => resolve({
        ok: true,
        json: async () => ({
          rounds: [{ instruction: '继续', prose: '他抬起头。' }], active_cast: [], live_round: null,
        }),
      } as Response) })
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

describe('stage1-outline toast must not fire when the target novel already has sandbox content', () => {
  beforeEach(() => {
    resolveHistory = null
    toastSuccessMock.mockClear()
    mockFetch()
    mockLocalStorage()
    sessionStorage.clear()
    localStorage.setItem('story-sandbox-mode:novel-A', 'chapter')
  })

  afterEach(() => {
    cleanup()
    vi.unstubAllGlobals()
  })

  it('does not toast the outline while a novel switch is mid-hydrate for a chapter that already has rounds', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } })
    client.setQueryData<Novel[]>(['novels'], [{ id: 'novel-A', name: 'A', active: true }])
    const store = buildTestStore({ ui: { chapter: 1 } } as never)

    render(
      <Provider store={store}>
        <QueryClientProvider client={client}>
          <StorySandboxPage />
        </QueryClientProvider>
      </Provider>,
    )

    // Mirrors App.tsx's novel-switch effect: resetForNovelSwitch() (which dispatches
    // resetSandbox()) fires synchronously, before the panel's hydrate effect's own
    // sandboxChatHydrateBegin has had a chance to flip `hydrating` back to true.
    store.dispatch(resetSandbox())

    // Let the skeleton query (and everything else that isn't the deliberately-stalled history
    // fetch) settle. Wait on the actual signal (the mocked history fetch having been reached)
    // rather than a fixed delay -- a fixed real-timer wait is fragile under full-suite load,
    // where extra component mount cost (e.g. Radix Select's portal/positioning effects) can
    // push settling past a short arbitrary budget even though nothing is actually broken.
    await waitFor(() => expect(store.getState().sandbox.hydratedScope).toBeNull())
    await waitFor(() => expect(resolveHistory).not.toBeNull())

    // The history fetch -- and therefore real confirmation of whether this chapter already has
    // rounds -- still hasn't resolved. Nothing should have toasted yet.
    expect(toastSuccessMock).not.toHaveBeenCalled()

    resolveHistory!(undefined)
    await waitFor(() => expect(store.getState().sandbox.chat.rounds.length).toBeGreaterThan(0))

    // Give any further effects a chance to run before asserting the negative.
    await new Promise((r) => setTimeout(r, 50))
    expect(toastSuccessMock).not.toHaveBeenCalled()
  })
})
