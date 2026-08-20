import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { configureStore } from '@reduxjs/toolkit'
import setupChatReducer, {
  clearSetupChatPendingChoice, resetSetupChat, sendSetupChatMessage, resetSetupChatConversation,
  regenerateSetupChatTurn, setupChatRegenerateStarted, setupChatEventApplied,
  setupChatMessageQueued, setupChatDequeueAndStart, setupChatMessageQueueRemoved,
  setSetupChatAutoMode, fetchSetupChatStatus, fetchSetupChatMode, stopSetupChatTurn,
  selectSetupChatBusy, selectSetupChatAutoMode, selectSetupChatPendingChoice, selectSetupChatQueueDepth,
  hydrateSetupChat, selectSetupChatState,   selectSetupChatHydratedNovel, selectSetupChatHydrating, selectSetupChatHistoryLoadedNovel,
} from '@/features/chat/store/setupChatSlice'
import { wsEventReceived } from '@/shared/store/wsActions'
import { EMPTY_CHAT_STATE } from '@/features/chat/utils/setupChatState'

function buildStore() {
  return configureStore({ reducer: { setupChat: setupChatReducer } })
}

const initial = {
  busy: false, messageQueue: [], autoMode: false, pendingChoice: null, chat: EMPTY_CHAT_STATE,
  hydratedNovel: null, historyLoadedNovel: null, hydrating: false, hydrateEpoch: 0,
}

describe('setupChatSlice reducer', () => {
  it('starts idle', () => {
    expect(setupChatReducer(undefined, { type: '@@INIT' })).toEqual(initial)
  })

  it('setup_chat_* events flip busy true, done/error flip it back false', () => {
    let state = setupChatReducer(initial, wsEventReceived({ type: 'setup_chat_delta' }))
    expect(state.busy).toBe(true)
    state = setupChatReducer(state, wsEventReceived({ type: 'setup_chat_done' }))
    expect(state.busy).toBe(false)
  })

  it('setup_chat_choice records the pending question/options', () => {
    const state = setupChatReducer(
      initial,
      wsEventReceived({ type: 'setup_chat_choice', question: '继续吗？', options: ['是', '否'] }),
    )
    expect(state.pendingChoice).toEqual({ question: '继续吗？', options: ['是', '否'] })
  })

  it('setup_chat_mode_changed syncs autoMode regardless of hydratedNovel', () => {
    const prev = { ...initial, autoMode: true, hydratedNovel: 'novel-a' }
    // Backend fires this when a background reset (e.g. the idle novel memory scavenger
    // evicting an unrelated novel) silently flips the process-global AUTO flag off --
    // must resync even though the event carries no novel_id tying it to novel-a.
    const state = setupChatReducer(
      prev,
      wsEventReceived({ type: 'setup_chat_mode_changed', auto: false }),
    )
    expect(state.autoMode).toBe(false)
  })

  it('clearSetupChatPendingChoice clears it', () => {
    const prev = { ...initial, pendingChoice: { question: 'q', options: ['a'] } }
    expect(setupChatReducer(prev, clearSetupChatPendingChoice()).pendingChoice).toBeNull()
  })

  it('setupChatMessageQueued holds POST payload locally without adding a chat bubble', () => {
    const state = setupChatReducer(
      initial,
      setupChatMessageQueued({ text: '第二条', attachmentIds: ['a1'] }),
    )
    expect(state.messageQueue).toHaveLength(1)
    expect(state.messageQueue[0]?.text).toBe('第二条')
    expect(state.messageQueue[0]?.attachmentIds).toEqual(['a1'])
    expect(state.messageQueue[0]?.id).toBeTruthy()
    expect(state.chat.messages).toEqual([])
    expect(selectSetupChatQueueDepth({ setupChat: state } as never)).toBe(1)
  })

  it('setupChatDequeueAndStart shifts queue, adds bubble, and locks busy before POST', () => {
    const prev = {
      ...initial,
      messageQueue: [{ id: 'q1', text: '排队', attachmentIds: [] }],
    }
    const state = setupChatReducer(prev, setupChatDequeueAndStart())
    expect(state.messageQueue).toEqual([])
    expect(state.busy).toBe(true)
    expect(state.chat.status).toBe('思考中…')
    expect(state.chat.messages.at(-1)?.content).toBe('排队')
  })

  it('setupChatMessageQueueRemoved drops a queued item by id', () => {
    const prev = {
      ...initial,
      messageQueue: [
        { id: 'keep', text: '保留', attachmentIds: [] },
        { id: 'drop', text: '删除', attachmentIds: [] },
      ],
    }
    const state = setupChatReducer(prev, setupChatMessageQueueRemoved('drop'))
    expect(state.messageQueue.map((item) => item.id)).toEqual(['keep'])
  })

  it('resetSetupChat clears messageQueue', () => {
    const state = setupChatReducer(
      { ...initial, messageQueue: [{ id: 'q1', text: 'x', attachmentIds: [] }], busy: true },
      resetSetupChat('novel-a'),
    )
    expect(state.messageQueue).toEqual([])
    expect(state.busy).toBe(false)
  })

  it('resetSetupChat clears busy/pendingChoice/chat but leaves autoMode untouched', () => {
    const prev = {
      busy: true, autoMode: true, pendingChoice: { question: 'q', options: ['a'] },
      chat: { ...EMPTY_CHAT_STATE, status: '思考中…' }, hydratedNovel: 'novel-a',
      hydrating: false, hydrateEpoch: 1,
    }
    expect(setupChatReducer(prev, resetSetupChat())).toEqual({
      ...initial, autoMode: true, hydrateEpoch: 2,
    })
  })

  it('resetSetupChat with target novel immediately focuses WS filter on that novel', () => {
    const prev = {
      busy: true, autoMode: true, pendingChoice: null,
      chat: { ...EMPTY_CHAT_STATE, live: '旧书思考中' }, hydratedNovel: 'novel-a',
      hydrating: false, hydrateEpoch: 1,
    }
    const afterReset = setupChatReducer(prev, resetSetupChat('novel-b'))
    expect(afterReset.hydratedNovel).toBe('novel-b')
    expect(afterReset.chat).toEqual(EMPTY_CHAT_STATE)
    const state = setupChatReducer(
      afterReset,
      wsEventReceived({ type: 'setup_chat_token', delta: '泄漏', novel_id: 'novel-a' }),
    )
    expect(state.chat.live).toBeFalsy()
  })

  it('selectors read the slice', () => {
    const state = { setupChat: { ...initial, busy: true, autoMode: true } }
    expect(selectSetupChatBusy(state as never)).toBe(true)
    expect(selectSetupChatAutoMode(state as never)).toBe(true)
    expect(selectSetupChatPendingChoice(state as never)).toBeNull()
  })

  it('a live WS token event builds chat.live even with no prior hydrate', () => {
    const state = setupChatReducer(initial, wsEventReceived({ type: 'setup_chat_token', delta: '你好' }))
    expect(state.chat.live).toBe('你好')
  })

  it('ignores setup_chat_* events from another novel once hydrated', () => {
    const prev = {
      ...initial,
      hydratedNovel: 'novel-a',
      busy: true,
      chat: { ...EMPTY_CHAT_STATE, messages: [{ id: 'm1', role: 'user' as const, content: '你好' }] },
    }
    const state = setupChatReducer(
      prev,
      wsEventReceived({ type: 'setup_chat_final', content: '别的书回复', novel_id: 'novel-b' }),
    )
    expect(state.chat.messages).toHaveLength(1)
    expect(state.chat.messages[0]?.content).toBe('你好')
    expect(state.busy).toBe(true)
  })
})

describe('setupChatSlice live-chat hydration', () => {
  beforeEach(() => { vi.restoreAllMocks() })
  afterEach(() => { vi.unstubAllGlobals() })

  it('hydrates messages + replays a buffered live turn on first mount', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({
        messages: [{ id: 'm1', role: 'user', content: '你好' }],
        live_round: { instruction: '你好', events: [{ type: 'setup_chat_token', delta: '在的' }] },
      }),
    } as Response)
    const store = buildStore()
    await store.dispatch(hydrateSetupChat('novelA') as never)
    const chat = selectSetupChatState(store.getState())
    expect(chat.messages).toEqual([{ id: 'm1', role: 'user', content: '你好' }])
    expect(chat.live).toBe('在的')
    expect(selectSetupChatHydratedNovel(store.getState())).toBe('novelA')
    expect(selectSetupChatHydrating(store.getState())).toBe(false)
  })

  it('does not re-fetch for an already-hydrated novel', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true, json: async () => ({ messages: [], live_round: null }),
    } as Response)
    const store = buildStore()
    await store.dispatch(hydrateSetupChat('novelA') as never)
    await store.dispatch(hydrateSetupChat('novelA') as never)
    expect(fetchSpy).toHaveBeenCalledTimes(1)
  })

  it('still fetches history after resetSetupChat pre-sets hydratedNovel for WS filtering', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({
        messages: [{ id: 'm1', role: 'user', content: '你好' }],
        live_round: null,
      }),
    } as Response)
    const store = buildStore()
    store.dispatch(resetSetupChat('novelB'))
    await store.dispatch(hydrateSetupChat('novelB') as never)
    expect(fetchSpy).toHaveBeenCalledTimes(1)
    expect(selectSetupChatState(store.getState()).messages).toEqual([
      { id: 'm1', role: 'user', content: '你好' },
    ])
    expect(selectSetupChatHydratedNovel(store.getState())).toBe('novelB')
  })

  it('retries hydration after resetForNovelSwitch discards a stale in-flight fetch', async () => {
    let resolveFetch: ((value: Response) => void) | undefined
    const fetchSpy = vi.spyOn(global, 'fetch').mockImplementation(
      () => new Promise((resolve) => { resolveFetch = resolve }),
    )
    const store = buildStore()
    const inFlight = store.dispatch(hydrateSetupChat('novelB') as never)
    store.dispatch(resetSetupChat('novelB'))
    resolveFetch?.({
      ok: true,
      json: async () => ({ messages: [{ id: 'stale', role: 'user', content: '旧' }], live_round: null }),
    } as Response)
    await inFlight
    expect(selectSetupChatHistoryLoadedNovel(store.getState())).toBeNull()

    fetchSpy.mockResolvedValue({
      ok: true,
      json: async () => ({
        messages: [{ id: 'm1', role: 'user', content: '新' }],
        live_round: null,
      }),
    } as Response)
    await store.dispatch(hydrateSetupChat('novelB') as never)
    expect(selectSetupChatHistoryLoadedNovel(store.getState())).toBe('novelB')
    expect(selectSetupChatState(store.getState()).messages).toEqual([
      { id: 'm1', role: 'user', content: '新' },
    ])
  })

  it('finalizes empty history when fetch fails so novel-switch overlay can dismiss', async () => {
    vi.spyOn(global, 'fetch').mockRejectedValue(new Error('network down'))
    const store = buildStore()
    store.dispatch(resetSetupChat('novelB'))
    await store.dispatch(hydrateSetupChat('novelB') as never)
    expect(selectSetupChatHistoryLoadedNovel(store.getState())).toBe('novelB')
    expect(selectSetupChatHydrating(store.getState())).toBe(false)
    expect(selectSetupChatState(store.getState()).messages).toEqual([])
  })

  it('keeps live chat state intact across a hydrate-guard-skipped remount, then keeps folding real WS events', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true, json: async () => ({ messages: [], live_round: null }),
    } as Response)
    const store = buildStore()
    await store.dispatch(hydrateSetupChat('novelA') as never)
    store.dispatch(wsEventReceived({ type: 'setup_chat_token', delta: '你好' }))
    await store.dispatch(hydrateSetupChat('novelA') as never)
    expect(selectSetupChatState(store.getState()).live).toBe('你好')
  })

  it('hydrates a new novel independently, clearing the previous novel leftover chat', async () => {
    let call = 0
    vi.spyOn(global, 'fetch').mockImplementation(async () => {
      call += 1
      if (call === 1) {
        return {
          ok: true,
          json: async () => ({ messages: [{ id: 'm1', role: 'user', content: '你好' }], live_round: null }),
        } as Response
      }
      return { ok: true, json: async () => ({ messages: [], live_round: null }) } as Response
    })
    const store = buildStore()
    await store.dispatch(hydrateSetupChat('novelA') as never)
    expect(selectSetupChatState(store.getState()).messages).toHaveLength(1)
    await store.dispatch(hydrateSetupChat('novelB') as never)
    expect(selectSetupChatState(store.getState()).messages).toHaveLength(0)
    expect(selectSetupChatHydratedNovel(store.getState())).toBe('novelB')
  })

  it('restores pendingChoice from a persisted choice record with no answer yet', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({
        messages: [
          { id: 'u1', role: 'user', content: '你好' },
          { id: 'c1', role: 'choice', content: '继续吗？', options: ['是', '否'] },
        ],
        live_round: null,
      }),
    } as Response)
    const store = buildStore()
    await store.dispatch(hydrateSetupChat('novelA') as never)
    expect(selectSetupChatPendingChoice(store.getState())).toEqual({ question: '继续吗？', options: ['是', '否'] })
    expect(selectSetupChatState(store.getState()).messages).toEqual([{ id: 'u1', role: 'user', content: '你好' }])
  })

  it('does not restore pendingChoice once a user record answers it', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({
        messages: [
          { id: 'c1', role: 'choice', content: '继续吗？', options: ['是', '否'] },
          { id: 'u1', role: 'user', content: '是' },
        ],
        live_round: null,
      }),
    } as Response)
    const store = buildStore()
    await store.dispatch(hydrateSetupChat('novelA') as never)
    expect(selectSetupChatPendingChoice(store.getState())).toBeNull()
  })
})

describe('setupChatSlice thunks', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })
  afterEach(() => vi.unstubAllGlobals())

  it('sendSetupChatMessage sets busy true immediately, POSTs, returns {ok:true} on 2xx', async () => {
    ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, json: async () => ({}) })
    const store = buildStore()
    const promise = store.dispatch(sendSetupChatMessage({ text: '继续', attachmentIds: [] }) as never)
    expect(selectSetupChatBusy(store.getState() as never)).toBe(true)
    const result = await (promise as unknown as Promise<{ payload: { ok: boolean } }>)
    expect(result.payload).toEqual({ ok: true })
    expect(fetch).toHaveBeenCalledWith('/api/setup-chat/message', expect.objectContaining({ method: 'POST' }))
  })

  it('sendSetupChatMessage resets busy to false and returns the error on non-2xx', async () => {
    ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: false, status: 500, json: async () => ({ error: '挂了' }) })
    const store = buildStore()
    const result = await store.dispatch(sendSetupChatMessage({ text: 'x' }) as never) as { payload: { ok: boolean; error?: string } }
    expect(result.payload).toEqual({ ok: false, error: '挂了' })
    expect(selectSetupChatBusy(store.getState() as never)).toBe(false)
  })

  it('sendSetupChatMessage returns a network error on fetch throwing', async () => {
    ;(fetch as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('boom'))
    const store = buildStore()
    const result = await store.dispatch(sendSetupChatMessage({ text: 'x' }) as never) as { payload: { ok: boolean; error?: string } }
    expect(result.payload).toEqual({ ok: false, error: '无法连接后端' })
  })

  it('setSetupChatAutoMode POSTs and updates autoMode on success', async () => {
    ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, json: async () => ({ auto: true }) })
    const store = buildStore()
    await store.dispatch(setSetupChatAutoMode(true) as never)
    expect(selectSetupChatAutoMode(store.getState() as never)).toBe(true)
  })

  it('fetchSetupChatStatus sets busy from the response body', async () => {
    ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, json: async () => ({ busy: true }) })
    const store = buildStore()
    await store.dispatch(fetchSetupChatStatus() as never)
    expect(selectSetupChatBusy(store.getState() as never)).toBe(true)
  })

  it('fetchSetupChatMode sets autoMode from the response body', async () => {
    ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, json: async () => ({ auto: true }) })
    const store = buildStore()
    await store.dispatch(fetchSetupChatMode() as never)
    expect(selectSetupChatAutoMode(store.getState() as never)).toBe(true)
  })

  it('resetSetupChatConversation POSTs /api/setup-chat/reset and returns {ok:true}', async () => {
    ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, json: async () => ({}) })
    const store = buildStore()
    const result = await store.dispatch(resetSetupChatConversation() as never) as { payload: { ok: boolean } }
    expect(result.payload).toEqual({ ok: true })
    expect(fetch).toHaveBeenCalledWith('/api/setup-chat/reset', { method: 'POST' })
  })

  it('stopSetupChatTurn POSTs /api/setup-chat/stop and returns {ok:true}', async () => {
    ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, json: async () => ({}) })
    const store = buildStore()
    const result = await store.dispatch(stopSetupChatTurn() as never) as { payload: { ok: boolean } }
    expect(result.payload).toEqual({ ok: true })
    expect(fetch).toHaveBeenCalledWith('/api/setup-chat/stop', { method: 'POST' })
  })

  it('stopSetupChatTurn returns the error on non-2xx', async () => {
    ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: false, status: 500, json: async () => ({ error: '挂了' }) })
    const store = buildStore()
    const result = await store.dispatch(stopSetupChatTurn() as never) as { payload: { ok: boolean; error?: string } }
    expect(result.payload).toEqual({ ok: false, error: '挂了' })
  })

  it('regenerateSetupChatTurn POSTs text and returns {ok:true} on success', async () => {
    ;(fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, json: async () => ({}) })
    const store = buildStore()
    const result = await store.dispatch(regenerateSetupChatTurn('继续') as never) as { payload: { ok: boolean } }
    expect(result.payload).toEqual({ ok: true })
    expect(fetch).toHaveBeenCalledWith('/api/setup-chat/regenerate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: '继续' }),
    })
  })

  it('setupChatRegenerateStarted removes the assistant bubble and seeds status', () => {
    const store = buildStore()
    store.dispatch(setupChatEventApplied({
      type: 'setup_chat_final', content: '答案',
    } as never))
    const assistantId = selectSetupChatState(store.getState() as never).messages.at(-1)!.id
    store.dispatch(setupChatRegenerateStarted({ assistantMsgId: assistantId }))
    const chat = selectSetupChatState(store.getState() as never)
    expect(chat.messages.some((m) => m.id === assistantId)).toBe(false)
    expect(chat.status).toBe('思考中…')
  })
})
