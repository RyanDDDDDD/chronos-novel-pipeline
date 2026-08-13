import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { configureStore } from '@reduxjs/toolkit'
import sandboxReducer, {
  resetSandbox, selectSandboxBusy, selectSandboxLiveProfileMutations,
  hydrateSandboxChat, selectSandboxChat, selectSandboxActiveCast, selectSandboxHydratedScope,
  selectSandboxHydrating, sandboxChatTurnSubmitted,
} from '@/features/sandbox/store/sandboxSlice'
import { wsEventReceived } from '@/shared/store/wsActions'
import { EMPTY_CHAT_STATE } from '@/features/sandbox/utils/sandboxChatState'

const initial = {
  busy: false, liveProfileMutations: {}, chat: EMPTY_CHAT_STATE, activeCast: [],
  hydratedScope: null, hydrating: false, hydrateEpoch: 0,
}

function buildStore() {
  return configureStore({ reducer: { sandbox: sandboxReducer } })
}

describe('sandboxSlice reducer', () => {
  it('starts idle', () => {
    expect(sandboxReducer(undefined, { type: '@@INIT' })).toEqual(initial)
  })

  it('story_sandbox_* events flip busy true, done flips it back false', () => {
    let state = sandboxReducer(initial, wsEventReceived({ type: 'story_sandbox_token' }))
    expect(state.busy).toBe(true)
    state = sandboxReducer(state, wsEventReceived({ type: 'story_sandbox_done' }))
    expect(state.busy).toBe(false)
  })

  it('story_sandbox_suggestions_regenerating flips busy true, regenerated flips it back false', () => {
    let state = sandboxReducer(initial, wsEventReceived({ type: 'story_sandbox_suggestions_regenerating' }))
    expect(state.busy).toBe(true)
    state = sandboxReducer(state, wsEventReceived({ type: 'story_sandbox_suggestions_regenerated' }))
    expect(state.busy).toBe(false)
  })

  it('ignores unrelated ws events', () => {
    expect(sandboxReducer(initial, wsEventReceived({ type: 'setup_chat_token' }))).toEqual(initial)
  })

  it('resetSandbox clears busy, liveProfileMutations, chat, activeCast and hydratedScope', () => {
    const dirty = {
      busy: true, liveProfileMutations: { 甲: { fields: { race: '精灵' }, at: 1 } },
      chat: { ...EMPTY_CHAT_STATE, status: '思考中…' }, activeCast: ['甲'],
      hydratedScope: { novelId: 'novelA', chapter: 1, branchId: 'b1' }, hydrating: false, hydrateEpoch: 2,
    }
    expect(sandboxReducer(dirty, resetSandbox())).toEqual({ ...initial, hydrateEpoch: 3 })
  })

  it('sandboxChatTurnSubmitted locks suggestion pills atomically', () => {
    const chat = {
      ...EMPTY_CHAT_STATE,
      rounds: [{
        instruction: 'a', prose: 'p', characterStates: {}, suggestions: ['甲'],
      }],
    }
    const state = sandboxReducer(
      { ...initial, chat },
      sandboxChatTurnSubmitted({
        instruction: 'next', isOpeningTurn: false, submittedDirections: [],
      }),
    )
    expect(state.chat.rounds[0].suggestionsLocked).toBe(true)
    expect(state.chat.liveRound?.instruction).toBe('next')
  })

  it('sandboxChatTurnSubmitted folds a director-ready liveRound into locked rounds', () => {
    const chat = {
      ...EMPTY_CHAT_STATE,
      liveRound: {
        instruction: 'a',
        prose: 'p',
        characterStates: {},
        suggestions: ['甲'],
        initialStates: null,
        sceneState: {},
        initialSceneState: null,
        eventLogEntries: [],
        rollingSummaryAfter: '',
        recallContext: '',
        recalledSettings: [],
        profileMutation: null,
        id: 'r1',
      },
    }
    const state = sandboxReducer(
      { ...initial, chat },
      sandboxChatTurnSubmitted({
        instruction: 'next', isOpeningTurn: false, submittedDirections: [],
      }),
    )
    expect(state.chat.rounds).toHaveLength(1)
    expect(state.chat.rounds[0].suggestionsLocked).toBe(true)
    expect(state.chat.rounds[0].id).toBe('r1')
    expect(state.chat.liveRound?.instruction).toBe('next')
  })

  it('selectSandboxBusy reads the slice', () => {
    expect(selectSandboxBusy({ sandbox: initial } as never)).toBe(false)
  })

  it('story_sandbox_profile_mutation records fields per character with a timestamp', () => {
    const before = Date.now()
    const state = sandboxReducer(initial, wsEventReceived({
      type: 'story_sandbox_profile_mutation',
      mutation: { 甲: { race: '精灵' }, 乙: { gender: 'xeno' } },
    }))
    expect(state.liveProfileMutations.甲.fields).toEqual({ race: '精灵' })
    expect(state.liveProfileMutations.乙.fields).toEqual({ gender: 'xeno' })
    expect(state.liveProfileMutations.甲.at).toBeGreaterThanOrEqual(before)
  })

  it('story_sandbox_profile_mutation with a null mutation is a no-op', () => {
    const state = sandboxReducer(initial, wsEventReceived({
      type: 'story_sandbox_profile_mutation', mutation: null,
    }))
    expect(state.liveProfileMutations).toEqual({})
  })

  it('story_sandbox_rewrite_done also records mutation fields', () => {
    const state = sandboxReducer(initial, wsEventReceived({
      type: 'story_sandbox_rewrite_done', mutation: { 甲: { race: '精灵' } },
    }))
    expect(state.liveProfileMutations.甲.fields).toEqual({ race: '精灵' })
  })

  it('a later mutation for the same character overwrites the earlier one', () => {
    let state = sandboxReducer(initial, wsEventReceived({
      type: 'story_sandbox_profile_mutation', mutation: { 甲: { race: '精灵' } },
    }))
    state = sandboxReducer(state, wsEventReceived({
      type: 'story_sandbox_profile_mutation', mutation: { 甲: { gender: 'xeno' } },
    }))
    expect(state.liveProfileMutations.甲.fields).toEqual({ gender: 'xeno' })
  })

  it('selectSandboxLiveProfileMutations reads the slice', () => {
    const mutations = { 甲: { fields: { race: '精灵' }, at: 123 } }
    expect(selectSandboxLiveProfileMutations({ sandbox: { ...initial, liveProfileMutations: mutations } } as never))
      .toEqual(mutations)
  })

  it('a live WS token event builds liveRound.prose even with no prior hydrate', () => {
    const state = sandboxReducer(initial, wsEventReceived({ type: 'story_sandbox_token', delta: '他抬起头。' }))
    expect(state.chat.liveRound?.prose).toBe('他抬起头。')
  })
})

describe('sandboxSlice live-chat hydration', () => {
  beforeEach(() => { vi.restoreAllMocks() })
  afterEach(() => { vi.unstubAllGlobals() })

  it('hydrates rounds + replays a buffered turn-mode live_round on first mount', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({
        rounds: [],
        active_cast: ['甲'],
        live_round: {
          mode: 'turn', instruction: '甲乙在书房对峙',
          events: [
            { type: 'story_sandbox_initial_states', states: { 甲: { psychology: '外冷内热' } }, scene_state: {} },
          ],
        },
      }),
    } as Response)
    const store = buildStore()
    await store.dispatch(hydrateSandboxChat({ novelId: 'novelA', chapter: 1, branchId: 'b1' }) as never)
    const chat = selectSandboxChat(store.getState())
    expect(chat.liveRound?.instruction).toBe('甲乙在书房对峙')
    expect(chat.liveRound?.initialStates).toEqual({ 甲: { psychology: '外冷内热' } })
    expect(chat.pendingFields).toEqual({})
    expect(selectSandboxActiveCast(store.getState())).toEqual(['甲'])
    expect(selectSandboxHydratedScope(store.getState())).toEqual({ novelId: 'novelA', chapter: 1, branchId: 'b1' })
    expect(selectSandboxHydrating(store.getState())).toBe(false)
  })

  it('shows the initial-state loading row (pendingFields.initialStates) when the opening turn has no events yet', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true,
      json: async () => ({
        rounds: [], active_cast: [],
        live_round: { mode: 'turn', instruction: '甲乙在书房对峙', events: [] },
      }),
    } as Response)
    const store = buildStore()
    await store.dispatch(hydrateSandboxChat({ novelId: 'novelA', chapter: 1, branchId: 'b1' }) as never)
    const chat = selectSandboxChat(store.getState())
    expect(chat.liveRound?.instruction).toBe('甲乙在书房对峙')
    expect(chat.pendingFields).toEqual({ initialStates: true, initialSceneState: true })
  })

  it('does not re-fetch on a second hydrate call for the same already-hydrated scope', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true, json: async () => ({ rounds: [], active_cast: [], live_round: null }),
    } as Response)
    const store = buildStore()
    await store.dispatch(hydrateSandboxChat({ novelId: 'novelA', chapter: 1, branchId: 'b1' }) as never)
    await store.dispatch(hydrateSandboxChat({ novelId: 'novelA', chapter: 1, branchId: 'b1' }) as never)
    expect(fetchSpy).toHaveBeenCalledTimes(1)
  })

  it('is a no-op when branchId is empty (e.g. a fresh chapter with no story-branch created yet)', async () => {
    const fetchSpy = vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true, json: async () => ({ rounds: [{ instruction: 'x', prose: 'y' }], active_cast: [], live_round: null }),
    } as Response)
    const store = buildStore()
    await store.dispatch(hydrateSandboxChat({ novelId: 'novelA', chapter: 1, branchId: '' }) as never)
    expect(fetchSpy).not.toHaveBeenCalled()
    expect(selectSandboxHydratedScope(store.getState())).toBeNull()
    expect(selectSandboxChat(store.getState())).toEqual(EMPTY_CHAT_STATE)
  })

  it('keeps live chat state intact across a hydrate-guard-skipped remount, then keeps folding real WS events', async () => {
    vi.spyOn(global, 'fetch').mockResolvedValue({
      ok: true, json: async () => ({ rounds: [], active_cast: [], live_round: null }),
    } as Response)
    const store = buildStore()
    await store.dispatch(hydrateSandboxChat({ novelId: 'novelA', chapter: 1, branchId: 'b1' }) as never)
    // A real turn starts and streams while nothing has unmounted -- the middleware would
    // normally dispatch this; here we dispatch it directly to isolate the reducer.
    store.dispatch(wsEventReceived({ type: 'story_sandbox_token', delta: '他抬起头。' }))
    // "Remount": call hydrate again for the same scope -- must be a no-op (guard skip), so the
    // live prose accumulated above must survive untouched.
    await store.dispatch(hydrateSandboxChat({ novelId: 'novelA', chapter: 1, branchId: 'b1' }) as never)
    expect(selectSandboxChat(store.getState()).liveRound?.prose).toBe('他抬起头。')
  })

  it('hydrates a new scope independently, clearing the previous scope leftover chat', async () => {
    let call = 0
    vi.spyOn(global, 'fetch').mockImplementation(async () => {
      call += 1
      if (call === 1) {
        return {
          ok: true,
          json: async () => ({
            rounds: [{ instruction: '继续', prose: '他抬起头。' }], active_cast: [], live_round: null,
          }),
        } as Response
      }
      return { ok: true, json: async () => ({ rounds: [], active_cast: [], live_round: null }) } as Response
    })
    const store = buildStore()
    await store.dispatch(hydrateSandboxChat({ novelId: 'novelA', chapter: 1, branchId: 'b1' }) as never)
    expect(selectSandboxChat(store.getState()).rounds).toHaveLength(1)
    await store.dispatch(hydrateSandboxChat({ novelId: 'novelA', chapter: 2, branchId: 'b1' }) as never)
    expect(selectSandboxChat(store.getState()).rounds).toHaveLength(0)
    expect(selectSandboxHydratedScope(store.getState())).toEqual({ novelId: 'novelA', chapter: 2, branchId: 'b1' })
  })

  it('regression: a resetSandbox() landing while a hydrate fetch is in flight discards the result and nothing ever retries it', async () => {
    // Reproduces "switch novels -> conversation history stays empty until F5": App.tsx now
    // optimistically flips useActiveNovelId() before POST /api/novels/active resolves (see
    // App.tsx's novel-switch effect), so StorySandboxPanel's hydrate effect can fire and START
    // fetching the new scope's history BEFORE resetForNovelSwitch() (dispatched only once that
    // REST call succeeds) gets around to clearing state.chat + bumping hydrateEpoch. When the
    // in-flight fetch's result lands after that reset, hydrateSandboxChat's own stale-epoch
    // guard correctly discards it (right call, in isolation) -- but nothing else ever re-issues
    // the hydrate, since StorySandboxPanel's effect only re-fires on a novelId/chapter/branchId
    // change, none of which change again after the switch has already settled. Net effect:
    // state.chat stays EMPTY_CHAT_STATE forever, exactly matching the reported bug.
    let resolveFetch: ((v: unknown) => void) | null = null
    vi.spyOn(global, 'fetch').mockImplementation(() => new Promise((resolve) => {
      resolveFetch = () => resolve({
        ok: true,
        json: async () => ({
          rounds: [{ instruction: '继续', prose: '他抬起头。' }], active_cast: [], live_round: null,
        }),
      } as Response)
    }))
    const store = buildStore()

    const hydratePromise = store.dispatch(
      hydrateSandboxChat({ novelId: 'novelB', chapter: 1, branchId: 'b1' }) as never,
    ) as unknown as Promise<void>

    // resetForNovelSwitch() lands while the fetch above is still pending.
    store.dispatch(resetSandbox())

    resolveFetch!(undefined)
    await hydratePromise

    expect(selectSandboxChat(store.getState())).toEqual(EMPTY_CHAT_STATE)
    expect(selectSandboxHydratedScope(store.getState())).toBeNull()
  })
})
