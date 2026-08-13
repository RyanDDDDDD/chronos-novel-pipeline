import { createSlice, createAsyncThunk } from '@reduxjs/toolkit'
import type { RootState } from '@/shared/store/store'
import { wsEventReceived, type OrchestratorEvent } from '@/shared/store/wsActions'
import { reduceSandboxBusy } from '@/features/sandbox/utils/sandboxBusy'
import {
  EMPTY_CHAT_STATE, EMPTY_LIVE_ROUND, reduceStorySandboxEvent, lockHistoricalRoundSuggestions,
  lockSuggestionsBeforeSend,
  type ChatState,
} from '@/features/sandbox/utils/sandboxChatState'
import type { StorySandboxEvent } from '@/features/sandbox/utils/storySandboxHistory'
import { inferSubmittedDirections } from '@/features/sandbox/utils/reconstructSubmittedDirections'
import { markDerivationsPending } from '@/features/sandbox/utils/sandboxDeriveFields'
import { fetchStorySandboxHistory } from '@/features/sandbox/utils/storySandboxHistory'

export interface LiveProfileMutation {
  fields: Record<string, unknown>
  at: number
}

export type SandboxScope = { novelId: string; chapter: number; branchId: string }
export type SandboxLiveMode = 'turn' | 'rewrite' | 'suggestions_regenerate' | 'selection_rewrite' | 'profile_mutation_rewrite'

interface SandboxState {
  busy: boolean
  liveProfileMutations: Record<string, LiveProfileMutation>
  chat: ChatState
  activeCast: string[]
  hydratedScope: SandboxScope | null
  hydrating: boolean
  hydrateEpoch: number
}

const initialState: SandboxState = {
  busy: false, liveProfileMutations: {}, chat: EMPTY_CHAT_STATE, activeCast: [],
  hydratedScope: null, hydrating: false, hydrateEpoch: 0,
}

function sameScope(a: SandboxScope | null, b: SandboxScope): boolean {
  return a !== null && a.novelId === b.novelId && a.chapter === b.chapter && a.branchId === b.branchId
}

const sandboxSlice = createSlice({
  name: 'sandbox',
  initialState,
  reducers: {
    /** Used by the cross-slice resetForNovelSwitch combo -- mirrors resetSetupChat. */
    resetSandbox: (state) => {
      state.busy = false; state.liveProfileMutations = {}
      state.chat = EMPTY_CHAT_STATE; state.activeCast = []
      state.hydratedScope = null; state.hydrating = false; state.hydrateEpoch += 1
    },
    sandboxChatHydrateBegin: (state, action: { payload: SandboxScope }) => {
      state.hydrating = true
      state.hydratedScope = action.payload
    },
    sandboxChatHydrateAbort: (state) => {
      state.hydrating = false
      state.hydratedScope = null
    },
    sandboxChatHydrateSeeded: (
      state,
      action: { payload: { rounds: ChatState['rounds']; activeCast: string[] } },
    ) => {
      state.chat = { ...EMPTY_CHAT_STATE, rounds: action.payload.rounds }
      state.activeCast = action.payload.activeCast
    },
    sandboxChatLiveSeeded: (
      state,
      action: { payload: { mode: SandboxLiveMode; instruction: string } },
    ) => {
      const { mode, instruction } = action.payload
      if (mode === 'rewrite') {
        state.chat.rewritingProse = ''
        state.chat.pendingFields = markDerivationsPending({}, ['characterStates', 'sceneState', 'suggestions'])
      } else if (mode === 'selection_rewrite') {
        state.chat.selectionRewriting = true
      } else if (mode === 'suggestions_regenerate') {
        state.chat.pendingFields = markDerivationsPending(state.chat.pendingFields, ['suggestions'])
      } else {
        state.chat.liveRound = { ...EMPTY_LIVE_ROUND, instruction }
        state.chat.status = '思考中…'
        state.chat.pendingFields = markDerivationsPending(
          {}, state.chat.rounds.length === 0 ? ['initialStates', 'initialSceneState'] : [],
        )
      }
    },
    sandboxChatHydrateFinalized: (state) => { state.hydrating = false },
    /** Optimistic local transitions that used to be local setState() calls in the panel --
     * mirrors authorLoop's runBegin/etc reducers. The actual network call still happens in the
     * panel via the existing sendMessage/etc props; these just update the Redux-held chat. */
    sandboxChatTurnSubmitted: (
      state,
      action: {
        payload: { instruction: string; isOpeningTurn: boolean; submittedDirections: string[] }
      },
    ) => {
      const { instruction, isOpeningTurn, submittedDirections } = action.payload
      state.chat.rounds = lockSuggestionsBeforeSend(state.chat, submittedDirections)
      state.chat.status = '思考中…'
      state.chat.liveRound = { ...EMPTY_LIVE_ROUND, instruction }
      state.chat.pendingFields = markDerivationsPending(
        {}, isOpeningTurn ? ['initialStates', 'initialSceneState'] : [],
      )
    },
    sandboxChatReset: (state) => { state.chat = EMPTY_CHAT_STATE; state.activeCast = [] },
    /** Folds any StorySandboxEvent-shaped action into chat via the same pure reducer real WS
     * traffic uses -- covers every manual error-injection call site the panel used to do via
     * `setState((s) => reduceStorySandboxEvent(s, {...}))` on a failed network call (submit/
     * reset/rewrite/regenerate/selection-rewrite all reuse this one action). */
    sandboxChatEventApplied: (state, action: { payload: StorySandboxEvent }) => {
      state.chat = reduceStorySandboxEvent(state.chat, action.payload)
    },
    sandboxChatRewriteStarted: (state) => {
      state.chat.rewritingProse = ''
      state.chat.pendingFields = markDerivationsPending({}, ['characterStates', 'sceneState', 'suggestions'])
    },
    sandboxChatRegenerateStarted: (state) => {
      state.chat.pendingFields = markDerivationsPending(state.chat.pendingFields, ['suggestions'])
    },
    sandboxChatProfileMutationRewriteStarted: (state) => {
      state.chat.profileMutationRewriting = true
    },
    sandboxChatSelectionRewriteFired: (
      state,
      action: { payload: { roundId: string; originalText: string; anchorOffset: number } },
    ) => {
      state.chat.selectionRewriting = true
      state.chat.selectionRewritingRoundId = action.payload.roundId
      state.chat.selectionRewritingAnchor = {
        originalText: action.payload.originalText,
        anchorOffset: action.payload.anchorOffset,
      }
      state.chat.pendingSelectionRewrite = null
    },
    sandboxChatSelectionRewriteQueued: (
      state,
      action: { payload: { roundId: string; originalText: string; anchorOffset: number; feedback: string } },
    ) => {
      state.chat.pendingSelectionRewrite = action.payload
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(wsEventReceived, (state, action) => {
        const data = action.payload
        if (!data.type.startsWith('story_sandbox_')) return
        state.busy = reduceSandboxBusy(state.busy, data)
        const mutationPayload = (() => {
          if (data.type === 'story_sandbox_profile_mutation_rewrite_done') {
            return (data as { profile_mutation?: Record<string, Record<string, unknown>> | null }).profile_mutation
          }
          if (data.type === 'story_sandbox_profile_mutation' || data.type === 'story_sandbox_rewrite_done') {
            return (data as { mutation?: Record<string, Record<string, unknown>> | null }).mutation
          }
          return null
        })()
        if (mutationPayload) {
          const at = Date.now()
          for (const [name, fields] of Object.entries(mutationPayload)) {
            state.liveProfileMutations[name] = { fields, at }
          }
        }
        state.chat = reduceStorySandboxEvent(state.chat, data as unknown as StorySandboxEvent)
        const ac = (data as unknown as { active_cast?: unknown }).active_cast
        if (
          Array.isArray(ac)
          && (data.type === 'story_sandbox_final' || data.type === 'story_sandbox_states'
            || data.type === 'story_sandbox_rewrite_done')
        ) {
          state.activeCast = ac as string[]
        }
      })
  },
})

export const {
  resetSandbox, sandboxChatHydrateBegin, sandboxChatHydrateAbort, sandboxChatHydrateSeeded,
  sandboxChatLiveSeeded, sandboxChatHydrateFinalized, sandboxChatTurnSubmitted,
  sandboxChatReset, sandboxChatEventApplied, sandboxChatRewriteStarted,
  sandboxChatRegenerateStarted, sandboxChatProfileMutationRewriteStarted,
  sandboxChatSelectionRewriteFired, sandboxChatSelectionRewriteQueued,
} = sandboxSlice.actions

/** Fetches this scope's REST history exactly once and seeds it into Redux, replaying any
 * already-buffered live-turn events through the same wsEventReceived reducer real WS traffic
 * uses -- mirrors authorLoopSlice's hydrateAuthorLoop. Once hydratedScope matches, a second call
 * (e.g. a remount) is a no-op: the store was never destroyed, so there's nothing to catch up on.
 * A falsy branchId (no story-branch resolved yet, e.g. a fresh chapter with none created) is a
 * no-op too -- mirrors the old useStorySandboxHistory query's `enabled: !!novelId && !!branchId`. */
export const hydrateSandboxChat = createAsyncThunk(
  'sandbox/hydrateChat',
  async (scope: SandboxScope, { dispatch, getState }) => {
    if (!scope.novelId || !scope.branchId) return
    const read = () => (getState() as RootState).sandbox
    if (sameScope(read().hydratedScope, scope)) return
    dispatch(sandboxChatHydrateBegin(scope))
    const epoch = read().hydrateEpoch
    const stale = (): boolean =>
      read().hydrateEpoch !== epoch || !sameScope(read().hydratedScope, scope)
    try {
      const data = await fetchStorySandboxHistory(scope.chapter, scope.branchId, scope.novelId)
      if (stale()) return
      dispatch(sandboxChatHydrateSeeded({
        rounds: lockHistoricalRoundSuggestions(inferSubmittedDirections(data.rounds)),
        activeCast: data.active_cast,
      }))
      const live = data.liveRound
      if (live) {
        dispatch(sandboxChatLiveSeeded({ mode: live.mode, instruction: live.instruction }))
        for (const ev of live.events) {
          if (stale()) return
          dispatch(wsEventReceived(ev as unknown as OrchestratorEvent))
        }
      }
      dispatch(sandboxChatHydrateFinalized())
    } catch {
      if (!stale()) {
        dispatch(sandboxChatHydrateSeeded({ rounds: [], activeCast: [] }))
        dispatch(sandboxChatHydrateFinalized())
      } else {
        dispatch(sandboxChatHydrateAbort())
      }
    }
  },
)

export const selectSandboxBusy = (state: RootState): boolean => state.sandbox.busy
export const selectSandboxLiveProfileMutations = (
  state: RootState,
): Record<string, LiveProfileMutation> => state.sandbox.liveProfileMutations
export const selectSandboxChat = (state: RootState): ChatState => state.sandbox.chat
export const selectSandboxActiveCast = (state: RootState): string[] => state.sandbox.activeCast
export const selectSandboxHydrating = (state: RootState): boolean => state.sandbox.hydrating
export const selectSandboxHydratedScope = (state: RootState): SandboxScope | null =>
  state.sandbox.hydratedScope
export const selectSandboxHydrateEpoch = (state: RootState): number =>
  state.sandbox.hydrateEpoch
export default sandboxSlice.reducer
