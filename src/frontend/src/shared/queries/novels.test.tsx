import { describe, it, expect, vi, beforeEach } from 'vitest'
import { renderHook, waitFor, act } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, useLocation } from 'react-router-dom'
import React from 'react'

vi.mock('@/shared/utils/novels', () => ({
  fetchNovels: vi.fn(),
  createNovel: vi.fn(),
  copyNovel: vi.fn(),
  renameNovel: vi.fn(),
  deleteNovel: vi.fn(),
}))

const promptMock = vi.fn()
vi.mock('@/shared/hooks/useToast', () => ({
  useToast: () => ({
    toasts: [],
    dismiss: vi.fn(),
    success: vi.fn(),
    error: vi.fn(),
    confirm: vi.fn(),
    prompt: (...args: unknown[]) => promptMock(...args),
  }),
}))

import { fetchNovels } from '@/shared/utils/novels'
import { useNovels, useActiveNovelId, useNovelActions } from '@/shared/queries/novels'

function wrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  )
}

/** useNovelActions additionally reads useNavigate/useLocation/useParams, so it needs a router
 * context around the QueryClientProvider -- the plain query-only hooks above don't. */
function routerWrapper(initialPath = '/novel/a/pipeline') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialPath]}>{children}</MemoryRouter>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  vi.mocked(fetchNovels).mockResolvedValue([
    { id: 'a', name: 'A', active: false },
    { id: 'b', name: 'B', active: true },
  ])
})

describe('novels hooks', () => {
  it('useNovels 拉列表', async () => {
    const { result } = renderHook(() => useNovels(), { wrapper: wrapper() })
    await waitFor(() => expect(result.current.data?.length).toBe(2))
  })

  it('useActiveNovelId 取 active 的 id', async () => {
    const { result } = renderHook(() => useActiveNovelId(), { wrapper: wrapper() })
    await waitFor(() => expect(result.current).toBe('b'))
  })
})

describe('useNovelActions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    promptMock.mockResolvedValue(null)
  })

  it('createNovel does nothing when the user cancels the prompt', async () => {
    vi.mocked(fetchNovels).mockResolvedValue([{ id: 'a', name: 'A', active: true }])
    promptMock.mockResolvedValue(null)
    const { createNovel } = await import('@/shared/utils/novels')
    const { result } = renderHook(() => useNovelActions(), { wrapper: routerWrapper() })
    await waitFor(() => expect(result.current).toBeTruthy())
    await act(async () => { await result.current.createNovel() })
    expect(createNovel).not.toHaveBeenCalled()
  })

  it('createNovel navigates to the new id under the chat view on success', async () => {
    vi.mocked(fetchNovels).mockResolvedValue([{ id: 'a', name: 'A', active: true }])
    promptMock.mockResolvedValue('新小说')
    const { createNovel } = await import('@/shared/utils/novels')
    vi.mocked(createNovel).mockResolvedValue({ ok: true, id: 'new-id' })
    const seenPath = { current: '' }
    function LocationProbe() {
      seenPath.current = useLocation().pathname
      return null
    }
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const w = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/novel/a/author']}>
          {children}
          <LocationProbe />
        </MemoryRouter>
      </QueryClientProvider>
    )
    const { result } = renderHook(() => useNovelActions(), { wrapper: w })
    await waitFor(() => expect(result.current).toBeTruthy())
    await act(async () => { await result.current.createNovel() })
    expect(createNovel).toHaveBeenCalledWith('新小说', false)
    expect(seenPath.current).toBe('/novel/new-id/chat')
    expect(promptMock).toHaveBeenCalledWith('新小说名称', expect.objectContaining({ confirmLabel: '创建' }))
  })

  it('renameNovel is a no-op when the prompt returns the unchanged current name', async () => {
    vi.mocked(fetchNovels).mockResolvedValue([{ id: 'a', name: 'A', active: true }])
    promptMock.mockResolvedValue('A')
    const { renameNovel } = await import('@/shared/utils/novels')
    const { result } = renderHook(
      () => ({ actions: useNovelActions(), novels: useNovels() }),
      { wrapper: routerWrapper() },
    )
    // renameNovel looks up the target's current name from the novels list, so wait for
    // the mocked fetchNovels() list to actually land before invoking it.
    await waitFor(() => expect(result.current.novels.data?.length).toBe(1))
    await act(async () => { await result.current.actions.renameNovel('a') })
    expect(renameNovel).not.toHaveBeenCalled()
  })

  it('deleteNovel is a no-op when called with an empty target id', async () => {
    vi.mocked(fetchNovels).mockResolvedValue([{ id: 'a', name: 'A', active: true }])
    const { deleteNovel } = await import('@/shared/utils/novels')
    const { result } = renderHook(() => useNovelActions(), { wrapper: routerWrapper() })
    await waitFor(() => expect(result.current).toBeTruthy())
    await act(async () => { await result.current.deleteNovel('') })
    expect(deleteNovel).not.toHaveBeenCalled()
  })
})

import { Provider } from 'react-redux'
import { buildTestStore } from '@/test/renderWithClient'
import { useNovelStatusSnapshot } from '@/shared/queries/novels'

function storeWrapper() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const store = buildTestStore()
  return {
    store,
    Wrapper: ({ children }: { children: React.ReactNode }) => (
      <Provider store={store}>
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      </Provider>
    ),
  }
}

describe('useNovelStatusSnapshot', () => {
  it('dispatches backgroundJobsSnapshotLoaded alongside novelStatusSnapshotLoaded', async () => {
    const payload = {
      n1: {
        author_loop: false, setup_chat: false, story_sandbox: false,
        skeleton_review: true, timeline_cascade: false, world_review: false, character_review: false,
      },
    }
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: true, json: async () => payload,
    })) as unknown as typeof fetch)

    const { store, Wrapper } = storeWrapper()
    const { result } = renderHook(() => useNovelStatusSnapshot(), { wrapper: Wrapper })

    await waitFor(() => expect(result.current.isSuccess).toBe(true))

    expect(store.getState().novelStatus.byNovelId.n1).toBeUndefined()
    expect(store.getState().backgroundJobs.byNovelId.n1).toEqual({
      skeletonReviewActive: true, timelineCascadeActive: false, worldReviewActive: false, characterReviewActive: false,
    })
  })
})
