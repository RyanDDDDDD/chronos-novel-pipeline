import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { configureStore } from '@reduxjs/toolkit'
import authorLoopReducer, {
  authorLoopRunBegin, authorLoopLiveRunSet, selectAuthorLoop, selectAuthorLoopLastAutoSave,
} from '@/features/author/store/authorLoopSlice'
import uiReducer, { setChapter } from '@/shared/store/uiSlice'
import connectionReducer, { wsConnected } from '@/shared/store/connectionSlice'
import setupChatReducer from '@/features/chat/store/setupChatSlice'
import { wsEventReceived } from '@/shared/store/wsActions'
import { listenerMiddleware } from '@/shared/store/listeners'
import { buildTestStore } from '@/test/renderWithClient'
import { EMPTY_CHAT_STATE } from '@/features/chat/utils/setupChatState'

function buildStore() {
  return configureStore({
    reducer: { authorLoop: authorLoopReducer, ui: uiReducer },
    middleware: (getDefault) => getDefault().prepend(listenerMiddleware.middleware),
  })
}

describe('listeners: watchdog', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('flags stalled after STALL_WARN_MS with no author_loop_* traffic while running', () => {
    const store = buildStore()
    store.dispatch(authorLoopRunBegin(3))
    vi.advanceTimersByTime(80_000)
    expect(selectAuthorLoop(store.getState() as never).stalled).toBe(true)
  })

  it('does not flag stalled if an author_loop_* event lands before the threshold', () => {
    const store = buildStore()
    store.dispatch(authorLoopRunBegin(3))
    vi.advanceTimersByTime(40_000)
    store.dispatch(wsEventReceived({ type: 'author_loop_progress', agent: 'write', attempt: 1, attempts: 1 }))
    vi.advanceTimersByTime(40_000)
    expect(selectAuthorLoop(store.getState() as never).stalled).toBeFalsy()
  })

  it('stops polling once the run leaves running (no further stalled flips)', () => {
    const store = buildStore()
    store.dispatch(authorLoopRunBegin(3))
    store.dispatch(wsEventReceived({ type: 'author_loop_stopped' }))
    vi.advanceTimersByTime(80_000)
    expect(selectAuthorLoop(store.getState() as never).stalled).toBeFalsy()
  })
})

describe('listeners: initial fetch on connect + resumable refresh on status settle', () => {
  beforeEach(() => vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ resumable: [2], busy: false, auto: false }) })))
  afterEach(() => vi.unstubAllGlobals())

  it('dispatching wsConnected fetches author-loop status + setup-chat status/mode + novels/status', async () => {
    const store = configureStore({
      reducer: { authorLoop: authorLoopReducer, ui: uiReducer, connection: connectionReducer, setupChat: setupChatReducer },
      middleware: (getDefault) => getDefault().prepend(listenerMiddleware.middleware),
    })
    store.dispatch(wsConnected())
    await vi.waitFor(() => {
      expect(fetch).toHaveBeenCalledWith('/api/author-loop/status')
      expect(fetch).toHaveBeenCalledWith('/api/setup-chat/status')
      expect(fetch).toHaveBeenCalledWith('/api/setup-chat/mode')
      expect(fetch).toHaveBeenCalledWith('/api/novels/status')
    })
  })

  it('re-fetches resumable chapters once status settles into done or idle', async () => {
    const store = configureStore({
      reducer: { authorLoop: authorLoopReducer, ui: uiReducer, connection: connectionReducer, setupChat: setupChatReducer },
      middleware: (getDefault) => getDefault().prepend(listenerMiddleware.middleware),
    })
    store.dispatch(authorLoopRunBegin(4))
    ;(fetch as ReturnType<typeof vi.fn>).mockClear()
    store.dispatch(wsEventReceived({ type: 'author_loop_done' }))
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/author-loop/status'))
  })
})

describe('listeners: chapter select sync', () => {
  beforeEach(() => vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ events: [] }) })))
  afterEach(() => vi.unstubAllGlobals())

  it('dispatching setChapter while idle triggers syncAuthorLoopForChapter (hydrate fetch for a resumable chapter)', async () => {
    const store = configureStore({
      reducer: { authorLoop: authorLoopReducer, ui: uiReducer },
      middleware: (getDefault) => getDefault().prepend(listenerMiddleware.middleware),
      preloadedState: {
        authorLoop: { ...authorLoopReducer(undefined, { type: '@@INIT' }), resumableChapters: [9] },
        ui: { chapter: 1, setupTab: 'world' },
      } as never,
    })
    store.dispatch(setChapter(9))
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledWith('/api/author-loop/journal?chapter=9'))
  })
})

describe('listeners: author_loop_done auto-save orchestration', () => {
  beforeEach(() => vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ ok: true, path: '/x.md' }) })))
  afterEach(() => vi.unstubAllGlobals())

  it('saves and records lastAutoSave when the run was liveRun and finishes', async () => {
    const store = buildStore()
    store.dispatch(authorLoopRunBegin(4))
    store.dispatch(authorLoopLiveRunSet(true))
    store.dispatch(wsEventReceived({ type: 'author_loop_done' }))
    await vi.waitFor(() => expect(selectAuthorLoopLastAutoSave(store.getState() as never)).toEqual({ ok: true, chapter: 4 }))
    expect(fetch).toHaveBeenCalledWith('/api/author-loop/save', expect.objectContaining({ method: 'POST' }))
  })

  it('does nothing when the finished run was not liveRun (e.g. hydrate replay)', async () => {
    const store = buildStore()
    store.dispatch(authorLoopRunBegin(4))
    store.dispatch(wsEventReceived({ type: 'author_loop_done' }))
    await Promise.resolve()
    // Note: the separate "resumable refresh on status settle" listener also fires here (status
    // just moved running -> done) and legitimately calls /api/author-loop/status -- this test is
    // only about the auto-save listener, so it asserts the save endpoint specifically wasn't hit.
    expect(fetch).not.toHaveBeenCalledWith('/api/author-loop/save', expect.anything())
    expect(selectAuthorLoopLastAutoSave(store.getState() as never)).toBeNull()
  })

  it('clears liveRun when a running loop lands on idle/error without ever reaching done', () => {
    const store = buildStore()
    store.dispatch(authorLoopRunBegin(4))
    store.dispatch(authorLoopLiveRunSet(true))
    store.dispatch(wsEventReceived({ type: 'author_loop_error', error: 'x' }))
    expect(selectAuthorLoop(store.getState() as never).liveRun).toBe(false)
  })
})

describe('listeners: setup-chat message queue drain', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) }))
  })
  afterEach(() => vi.unstubAllGlobals())

  it('POSTs the head of the queue when busy clears, even without SetupChatPanel mounted', async () => {
    const store = buildTestStore({
      setupChat: {
        busy: true,
        messageQueue: [{ id: 'q1', text: '排队消息', attachmentIds: ['a1'] }],
        autoMode: false,
        pendingChoice: null,
        chat: EMPTY_CHAT_STATE,
        hydratedNovel: 'n1',
        historyLoadedNovel: 'n1',
        hydrating: false,
        hydrateEpoch: 0,
      },
    })
    store.dispatch(wsEventReceived({ type: 'setup_chat_done' }))
    await vi.waitFor(() => {
      expect(fetch).toHaveBeenCalledWith(
        '/api/setup-chat/message',
        expect.objectContaining({
          method: 'POST',
          body: JSON.stringify({ text: '排队消息', attachment_ids: ['a1'] }),
        }),
      )
    })
    expect(store.getState().setupChat.messageQueue).toEqual([])
  })
})

describe('listeners: portrait_generation_done invalidates cast query', () => {
  it('invalidates setup cast queries when portrait generation finishes', async () => {
    const invalidateSpy = vi.spyOn(
      (await import('@/shared/lib/queryClient')).queryClient,
      'invalidateQueries',
    )

    const store = buildTestStore()
    store.dispatch(wsEventReceived({
      type: 'portrait_generation_done', novel_id: 'novel-A', character: '甲', portrait_path: '甲-1.png',
    }))

    await vi.waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['setup', 'cast'] })
    })

    invalidateSpy.mockRestore()
  })
})

describe('listeners: novita_model_catalog_refreshed invalidates the catalog query', () => {
  it('invalidates the novita model catalog query when the refresh finishes', async () => {
    const invalidateSpy = vi.spyOn(
      (await import('@/shared/lib/queryClient')).queryClient,
      'invalidateQueries',
    )

    const store = buildTestStore()
    store.dispatch(wsEventReceived({ type: 'novita_model_catalog_refreshed' }))

    await vi.waitFor(() => {
      expect(invalidateSpy).toHaveBeenCalledWith({ queryKey: ['novita-model-catalog'] })
    })

    invalidateSpy.mockRestore()
  })
})
