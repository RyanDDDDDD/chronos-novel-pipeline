import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { configureStore } from '@reduxjs/toolkit'
import authorLoopReducer from '@/features/author/store/authorLoopSlice'
import setupChatReducer from '@/features/chat/store/setupChatSlice'
import sandboxReducer from '@/features/sandbox/store/sandboxSlice'
import tokenUsageReducer, { tokenUsageKey } from '@/shared/store/tokenUsageSlice'
import novelImportReducer from '@/features/chat/store/novelImportSlice'
import { resetForNovelSwitch } from '@/shared/store/resetForNovelSwitch'
import { EMPTY_CHAT_STATE } from '@/features/sandbox/utils/sandboxChatState'
import { EMPTY_CHAT_STATE as EMPTY_SETUP_CHAT_STATE } from '@/features/chat/utils/setupChatState'

function buildStore() {
  return configureStore({
    reducer: {
      authorLoop: authorLoopReducer,
      setupChat: setupChatReducer,
      sandbox: sandboxReducer,
      tokenUsage: tokenUsageReducer,
      novelImport: novelImportReducer,
    },
  })
}

describe('resetForNovelSwitch', () => {
  beforeEach(() => vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ resumable: [], busy: false, novel_import: null }),
  })))
  afterEach(() => vi.unstubAllGlobals())

  it('resets domain slices and re-fetches author-loop status', async () => {
    const preloaded = {
      setupChat: {
        busy: true, autoMode: false, pendingChoice: { question: 'q', options: ['a'] },
        chat: { ...EMPTY_SETUP_CHAT_STATE, status: '思考中…' }, hydratedNovel: 'novel-a',
        historyLoadedNovel: 'novel-a', hydrating: false, hydrateEpoch: 1,
      },
      sandbox: {
        busy: true, liveProfileMutations: {}, chat: EMPTY_CHAT_STATE, activeCast: ['甲'],
        hydratedScope: { novelId: 'novel-a', chapter: 1 }, hydrating: false, hydrateEpoch: 1,
      },
      tokenUsage: { [tokenUsageKey('a', 'b')]: { tokens_in: 1, tokens_out: 1, tokens_cached: 0, cost: 0 } },
    }
    const seeded = configureStore({
      reducer: {
        authorLoop: authorLoopReducer,
        setupChat: setupChatReducer,
        sandbox: sandboxReducer,
        tokenUsage: tokenUsageReducer,
        novelImport: novelImportReducer,
      },
      preloadedState: preloaded as never,
    })
    await seeded.dispatch(resetForNovelSwitch('novel-a') as never)
    const state = seeded.getState()
    expect(state.setupChat).toEqual({
      busy: false, messageQueue: [], autoMode: false, pendingChoice: null, chat: EMPTY_SETUP_CHAT_STATE,
      hydratedNovel: 'novel-a', historyLoadedNovel: null, hydrating: false, hydrateEpoch: 2,
    })
    expect(state.sandbox).toEqual({
      busy: false, liveProfileMutations: {}, chat: EMPTY_CHAT_STATE, activeCast: [],
      hydratedScope: null, hydrating: false, hydrateEpoch: 2,
    })
    expect(state.tokenUsage).toEqual({})
    expect(fetch).toHaveBeenCalledWith('/api/author-loop/status?novel_id=novel-a')
    expect(fetch).toHaveBeenCalledWith('/api/setup-chat/status?novel_id=novel-a')
  })

  it('resyncs setup_chat busy=true when the agent is still running for the switched-to novel', async () => {
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      if (url.startsWith('/api/setup-chat/status')) {
        return Promise.resolve({
          ok: true,
          json: async () => ({ busy: true, novel_import: null }),
        })
      }
      return Promise.resolve({ ok: true, json: async () => ({ resumable: [] }) })
    }))
    const store = buildStore()
    await store.dispatch(resetForNovelSwitch('novel-a') as never)
    expect(store.getState().setupChat.busy).toBe(true)
  })

  it('preserves novel import progress for other novels and resyncs the switched-to novel', async () => {
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      if (url === '/api/setup-chat/status?novel_id=novel-b') {
        return Promise.resolve({
          ok: true,
          json: async () => ({
            busy: false,
            novel_import: { status: 'running', kind: 'image', index: 2, total: 5 },
          }),
        })
      }
      return Promise.resolve({ ok: true, json: async () => ({ resumable: [] }) })
    }))
    const store = configureStore({
      reducer: {
        authorLoop: authorLoopReducer,
        setupChat: setupChatReducer,
        sandbox: sandboxReducer,
        tokenUsage: tokenUsageReducer,
        novelImport: novelImportReducer,
      },
      preloadedState: {
        novelImport: {
          byNovelId: {
            'novel-a': { status: 'running', kind: 'text', index: 10, total: 20 },
          },
        },
      } as never,
    })
    await store.dispatch(resetForNovelSwitch('novel-b') as never)
    const state = store.getState()
    expect(state.novelImport.byNovelId['novel-a']).toEqual({
      status: 'running', kind: 'text', index: 10, total: 20,
    })
    expect(state.novelImport.byNovelId['novel-b']).toEqual({
      status: 'running', kind: 'image', index: 2, total: 5,
    })
  })
})
