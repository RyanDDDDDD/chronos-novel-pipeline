import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Provider } from 'react-redux'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import React from 'react'
import { buildTestStore } from '@/test/renderWithClient'
import type { Novel } from '@/shared/utils/novels'

let resolveSwitch: ((v: { ok: boolean; error?: string }) => void) | null = null

vi.mock('@/shared/utils/novels', () => ({
  fetchNovels: vi.fn(async () => [
    { id: 'n1', name: 'N1', active: true },
    { id: 'n2', name: 'N2', active: false },
  ]),
  createNovel: vi.fn(),
  switchNovel: vi.fn(() => new Promise((resolve) => { resolveSwitch = resolve })),
  renameNovel: vi.fn(),
  deleteNovel: vi.fn(),
  filterNovelsByName: (novels: Novel[]) => novels,
}))
vi.mock('@/features/pipeline/components/PipelineWorkflowConfigView', () => ({ default: () => <div data-testid="author-loop-config" /> }))

beforeEach(() => {
  resolveSwitch = null
  vi.stubGlobal('fetch', vi.fn(async (url: string) => ({
    ok: true,
    json: async () =>
      url.includes('/api/chapters') ? { chapters: [{ chapter: 1, title: null }] } : {},
  })) as unknown as typeof fetch)
})

import App from './App'

function renderAppAt(initialPath: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 30_000 } } })
  client.setQueryData(['novels'], [
    { id: 'n1', name: 'N1', active: true },
    { id: 'n2', name: 'N2', active: false },
  ])
  const store = buildTestStore()
  render(
    <Provider store={store}>
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={[initialPath]}>
          <Routes>
            <Route path="/novel/:novelId/*" element={<App />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>
    </Provider>,
  )
  return { client, store }
}

describe('novel switch optimistic active-flag update', () => {
  it('flips the ["novels"] cache active flag before the POST /api/novels/active round-trip resolves', async () => {
    // URL says n2, but the seeded query cache still has n1 marked active -- this mismatch is
    // exactly what App's resolveNovelSwitch effect detects and reacts to on mount.
    const { client } = renderAppAt('/novel/n2/pipeline')

    await waitFor(() => {
      const novels = client.getQueryData<Novel[]>(['novels'])
      expect(novels?.find((n) => n.id === 'n2')?.active).toBe(true)
      expect(novels?.find((n) => n.id === 'n1')?.active).toBe(false)
    })

    // switchNovel's REST call hasn't resolved yet -- the optimistic flip above happened without
    // waiting for it.
    expect(resolveSwitch).not.toBeNull()

    resolveSwitch!({ ok: true })
    await waitFor(() => {
      const novels = client.getQueryData<Novel[]>(['novels'])
      expect(novels?.find((n) => n.id === 'n2')?.active).toBe(true)
    })
  })

  it('rolls back the optimistic flip if the switch request fails', async () => {
    const { client } = renderAppAt('/novel/n2/pipeline')

    await waitFor(() => {
      const novels = client.getQueryData<Novel[]>(['novels'])
      expect(novels?.find((n) => n.id === 'n2')?.active).toBe(true)
    })

    resolveSwitch!({ ok: false, error: '切换失败' })

    // On failure the effect re-invalidates ['novels'] -- refetch (mocked fetchNovels) returns
    // the server's real truth, n1 still active, n2 not.
    await waitFor(() => {
      const novels = client.getQueryData<Novel[]>(['novels'])
      expect(novels?.find((n) => n.id === 'n1')?.active).toBe(true)
      expect(novels?.find((n) => n.id === 'n2')?.active).toBe(false)
    })
  })

  it('dispatches resetForNovelSwitch synchronously with the optimistic flip, before switchNovel resolves', async () => {
    // Regression for "conversation history stays empty until F5": resetForNovelSwitch() used to
    // be dispatched only after switchNovel()'s REST call succeeded, well after the optimistic
    // active-flag flip above had already let StorySandboxPanel/SetupChatPanel start hydrating
    // the new novel's history. If that reset landed mid-hydrate, hydrateSandboxChat's own
    // stale-epoch guard correctly discarded the (by-then-late) result, but nothing ever
    // re-issued the hydrate -- the chat stayed empty forever. Firing the reset in the same
    // synchronous batch as the flip guarantees it always happens BEFORE any hydrate can start.
    const { client, store } = renderAppAt('/novel/n2/pipeline')

    await waitFor(() => {
      const novels = client.getQueryData<Novel[]>(['novels'])
      expect(novels?.find((n) => n.id === 'n2')?.active).toBe(true)
    })

    // The reset (sandboxSlice's resetSandbox bumps hydrateEpoch) must already have happened --
    // switchNovel's REST call is still pending at this point.
    expect(resolveSwitch).not.toBeNull()
    expect(store.getState().sandbox.hydrateEpoch).toBeGreaterThan(0)

    resolveSwitch!({ ok: true })
  })
})
