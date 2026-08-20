import { createAsyncThunk, createSlice, type PayloadAction } from '@reduxjs/toolkit'
import type { RootState } from '@/shared/store/store'
import { wsEventReceived, type OrchestratorEvent } from '@/shared/store/wsActions'
import { reduceSetupChatBusy } from '@/features/chat/utils/setupChatBusy'
import { reduceSetupChatPendingChoice, derivePendingChoiceFromMessages, type PendingChoice } from '@/features/chat/utils/setupChatPendingChoice'
import {
  EMPTY_CHAT_STATE, newMsgId, reduceChatEvent, normalizeChatMessages, type ChatState,
} from '@/features/chat/utils/setupChatState'
import { fetchSetupChatHistory } from '@/shared/utils/setup'
import type { ChatEvent } from '@/shared/utils/setup'

export type SetupChatQueuedMessage = {
  id: string
  text: string
  attachmentIds: string[]
}

interface SetupChatState {
  busy: boolean
  /** User messages waiting to POST until the current turn finishes (frontend-only queue). */
  messageQueue: SetupChatQueuedMessage[]
  autoMode: boolean
  pendingChoice: PendingChoice
  chat: ChatState
  hydratedNovel: string | null
  /** REST history for hydratedNovel has been fetched at least once (distinct from hydratedNovel,
   * which resetSetupChat(novelId) pre-sets for WS filtering before the fetch runs). */
  historyLoadedNovel: string | null
  hydrating: boolean
  hydrateEpoch: number
}

const initialState: SetupChatState = {
  busy: false, messageQueue: [], autoMode: false, pendingChoice: null, chat: EMPTY_CHAT_STATE,
  hydratedNovel: null, historyLoadedNovel: null, hydrating: false, hydrateEpoch: 0,
}

export const sendSetupChatMessage = createAsyncThunk(
  'setupChat/sendMessage',
  async (
    { text, attachmentIds }: { text: string; attachmentIds?: string[] },
  ): Promise<{ ok: boolean; error?: string }> => {
    try {
      const res = await fetch('/api/setup-chat/message', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, attachment_ids: attachmentIds ?? [] }),
      })
      const body = await res.json().catch(() => ({}))
      if (!res.ok) {
        return { ok: false, error: (body as { error?: string }).error ?? `发送失败 (HTTP ${res.status})` }
      }
      return { ok: true }
    } catch {
      return { ok: false, error: '无法连接后端' }
    }
  },
)

export const resetSetupChatConversation = createAsyncThunk(
  'setupChat/resetConversation',
  async (): Promise<{ ok: boolean; error?: string }> => {
    try {
      const res = await fetch('/api/setup-chat/reset', { method: 'POST' })
      const body = await res.json().catch(() => ({}))
      if (!res.ok) {
        return { ok: false, error: (body as { error?: string }).error ?? `清空失败 (HTTP ${res.status})` }
      }
      return { ok: true }
    } catch {
      return { ok: false, error: '无法连接后端' }
    }
  },
)

export const stopSetupChatTurn = createAsyncThunk(
  'setupChat/stopTurn',
  async (): Promise<{ ok: boolean; error?: string }> => {
    try {
      const res = await fetch('/api/setup-chat/stop', { method: 'POST' })
      const body = await res.json().catch(() => ({}))
      if (!res.ok) {
        return { ok: false, error: (body as { error?: string }).error ?? `中断失败 (HTTP ${res.status})` }
      }
      return { ok: true }
    } catch {
      return { ok: false, error: '无法连接后端' }
    }
  },
)

export const regenerateSetupChatTurn = createAsyncThunk(
  'setupChat/regenerateTurn',
  async (text: string): Promise<{ ok: boolean; error?: string }> => {
    try {
      const res = await fetch('/api/setup-chat/regenerate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      })
      const body = await res.json().catch(() => ({}))
      if (!res.ok) {
        return { ok: false, error: (body as { error?: string }).error ?? `重新生成失败 (HTTP ${res.status})` }
      }
      return { ok: true }
    } catch {
      return { ok: false, error: '无法连接后端' }
    }
  },
)

export const setSetupChatAutoMode = createAsyncThunk(
  'setupChat/setAutoMode',
  async (auto: boolean): Promise<{ ok: boolean; auto?: boolean; error?: string }> => {
    try {
      const res = await fetch('/api/setup-chat/mode', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ auto }),
      })
      const body = await res.json().catch(() => ({}))
      if (!res.ok) {
        return { ok: false, error: (body as { error?: string }).error ?? `切换失败 (HTTP ${res.status})` }
      }
      return { ok: true, auto: body.auto === true }
    } catch {
      return { ok: false, error: '无法连接后端' }
    }
  },
)

export const fetchSetupChatStatus = createAsyncThunk(
  'setupChat/fetchStatus',
  async (novelId?: string) => {
    try {
      const qs = novelId ? `?novel_id=${encodeURIComponent(novelId)}` : ''
      const res = await fetch(`/api/setup-chat/status${qs}`)
      const body = await res.json().catch(() => ({}))
      return body.busy === true
    } catch {
      return undefined
    }
  },
)

export const fetchSetupChatMode = createAsyncThunk('setupChat/fetchMode', async () => {
  try {
    const res = await fetch('/api/setup-chat/mode')
    const body = await res.json().catch(() => ({}))
    return body.auto === true
  } catch {
    return undefined
  }
})

const setupChatSlice = createSlice({
  name: 'setupChat',
  initialState,
  reducers: {
    clearSetupChatPendingChoice: (state) => { state.pendingChoice = null },
    /** Used by the cross-slice resetForNovelSwitch combo (Task 6) -- mirrors resetSandbox.
     * autoMode is deliberately untouched (novel switch doesn't change the auto-mode preference).
     * When payload is the switch target, hydratedNovel is set immediately so in-flight WS
     * events from the previous novel are dropped before hydrateSetupChat begins. */
    resetSetupChat: (state, action: PayloadAction<string | undefined>) => {
      state.busy = false; state.messageQueue = []; state.pendingChoice = null
      state.chat = EMPTY_CHAT_STATE
      state.hydratedNovel = action.payload ?? null
      state.historyLoadedNovel = null
      state.hydrating = false
      state.hydrateEpoch += 1
    },
    setupChatHydrateBegin: (state, action: { payload: string }) => {
      state.hydrating = true
      state.hydratedNovel = action.payload
    },
    setupChatHydrateAbort: (state) => {
      state.hydrating = false
      state.hydratedNovel = null
    },
    setupChatHydrateSeeded: (
      state,
      action: { payload: { messages: ChatState['messages']; pendingChoice: PendingChoice } },
    ) => {
      state.chat = { ...EMPTY_CHAT_STATE, messages: action.payload.messages }
      state.pendingChoice = action.payload.pendingChoice
    },
    setupChatHydrateFinalized: (state) => {
      state.hydrating = false
      state.historyLoadedNovel = state.hydratedNovel
    },
    /** Optimistic local transition mirroring the old setState() the panel did before the network
     * call -- the actual POST still happens via sendSetupChatMessage. Also seeds status so the
     * loading bubble shows immediately rather than staying invisible until a setup_chat_tool
     * progress event or the first token arrives (mirrors sandboxChatTurnSubmitted's status set) --
     * a plain reply with no tool call in between would otherwise show nothing at all while the
     * agent is generating. */
    setupChatMessageSubmitted: (state, action: { payload: { text: string; queued?: boolean } }) => {
      state.chat.messages.push({ id: newMsgId(), role: 'user', content: action.payload.text })
      if (!action.payload.queued) state.chat.status = '思考中…'
    },
    /** Hold the outbound POST in the composer queue until the agent is idle again. */
    setupChatMessageQueued: (state, action: { payload: { text: string; attachmentIds: string[] } }) => {
      state.messageQueue.push({
        id: newMsgId(),
        text: action.payload.text,
        attachmentIds: action.payload.attachmentIds,
      })
    },
    /** Shift the head of the frontend queue, show the user bubble, and mark busy before POST. */
    setupChatDequeueAndStart: (state) => {
      if (state.messageQueue.length === 0) return
      const next = state.messageQueue.shift()
      if (!next) return
      state.chat.messages.push({ id: newMsgId(), role: 'user', content: next.text })
      state.chat.status = '思考中…'
      state.busy = true
    },
    setupChatMessageQueueRemoved: (state, action: { payload: string }) => {
      state.messageQueue = state.messageQueue.filter((item) => item.id !== action.payload)
    },
    /** Clears just this novel's conversation content on a successful resetSetupChatConversation
     * -- distinct from resetSetupChat (novel switch), which also drops hydratedNovel/bumps
     * hydrateEpoch. Here the novel is still the hydrated one, only its content is wiped. */
    setupChatCleared: (state) => { state.chat = EMPTY_CHAT_STATE; state.messageQueue = [] },
    /** Folds any ChatEvent-shaped action into chat via the same pure reducer real WS traffic
     * uses -- covers the manual error-injection call sites (failed submit/reset). */
    setupChatEventApplied: (state, action: { payload: ChatEvent }) => {
      state.chat = reduceChatEvent(state.chat, action.payload)
    },
    /** Drop the assistant bubble being regenerated and show a fresh loading status. */
    setupChatRegenerateStarted: (state, action: { payload: { assistantMsgId: string } }) => {
      state.chat.messages = state.chat.messages.filter((m) => m.id !== action.payload.assistantMsgId)
      state.chat.live = ''
      state.chat.status = '思考中…'
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(wsEventReceived, (state, action) => {
        const data = action.payload
        if (!data.type.startsWith('setup_chat_')) return
        // auto mode is a process-global preference, not scoped to a novel (see mode.py) --
        // handle it before the per-novel filter below so a background reset (e.g. the idle
        // novel memory scavenger silently flipping it off) resyncs the button regardless of
        // which novel is currently hydrated.
        if (data.type === 'setup_chat_mode_changed') {
          if (data.auto !== undefined) state.autoMode = data.auto
          return
        }
        const eventNovelId = data.novel_id
        if (state.hydratedNovel && eventNovelId && eventNovelId !== state.hydratedNovel) return
        if (data.type === 'setup_chat_queued') return
        state.busy = reduceSetupChatBusy(state.busy, data)
        state.pendingChoice = reduceSetupChatPendingChoice(state.pendingChoice, data)
        state.chat = reduceChatEvent(state.chat, data as unknown as ChatEvent)
      })
      .addCase(sendSetupChatMessage.pending, (state) => { state.busy = true })
      .addCase(sendSetupChatMessage.fulfilled, (state, action) => {
        if (!action.payload.ok) state.busy = false
      })
      .addCase(regenerateSetupChatTurn.pending, (state) => { state.busy = true })
      .addCase(regenerateSetupChatTurn.fulfilled, (state, action) => {
        if (!action.payload.ok) state.busy = false
      })
      .addCase(setSetupChatAutoMode.fulfilled, (state, action) => {
        if (action.payload.ok && action.payload.auto !== undefined) state.autoMode = action.payload.auto
      })
      .addCase(fetchSetupChatStatus.fulfilled, (state, action) => {
        if (action.payload !== undefined) state.busy = action.payload
      })
      .addCase(fetchSetupChatMode.fulfilled, (state, action) => {
        if (action.payload !== undefined) state.autoMode = action.payload
      })
  },
})

export const {
  clearSetupChatPendingChoice, resetSetupChat, setupChatHydrateBegin, setupChatHydrateAbort,
  setupChatHydrateSeeded, setupChatHydrateFinalized, setupChatMessageSubmitted, setupChatMessageQueued,
  setupChatDequeueAndStart, setupChatMessageQueueRemoved, setupChatEventApplied,
  setupChatCleared, setupChatRegenerateStarted,
} = setupChatSlice.actions

/** Fetches this novel's REST history exactly once and seeds it into Redux, replaying any
 * already-buffered live-turn events through the same wsEventReceived reducer real WS traffic
 * uses -- mirrors authorLoopSlice's hydrateAuthorLoop / sandboxSlice's hydrateSandboxChat. Once
 * hydratedNovel matches, a second call (e.g. a remount) is a no-op. */
export const hydrateSetupChat = createAsyncThunk(
  'setupChat/hydrateChat',
  async (novelId: string, { dispatch, getState }) => {
    const read = () => (getState() as RootState).setupChat
    if (read().historyLoadedNovel === novelId) return
    dispatch(setupChatHydrateBegin(novelId))
    const epoch = read().hydrateEpoch
    const stale = (): boolean =>
      read().hydrateEpoch !== epoch || read().hydratedNovel !== novelId
    try {
      const data = await fetchSetupChatHistory(novelId)
      if (stale()) return
      const pendingChoice = derivePendingChoiceFromMessages(data.messages)
      const visibleMessages = data.messages.filter((m) => m.role !== 'choice') as Parameters<
        typeof normalizeChatMessages
      >[0]
      const messages = normalizeChatMessages(visibleMessages)
      dispatch(setupChatHydrateSeeded({ messages, pendingChoice }))
      if (data.liveRound) {
        for (const ev of data.liveRound.events) {
          if (stale()) return
          dispatch(wsEventReceived(ev as unknown as OrchestratorEvent))
        }
      }
      dispatch(setupChatHydrateFinalized())
    } catch {
      // Finalize with empty history so novel-switch overlay can dismiss; a stale failure must
      // not clobber state resetForNovelSwitch just applied for a different scope.
      if (!stale()) {
        dispatch(setupChatHydrateSeeded({ messages: [], pendingChoice: null }))
        dispatch(setupChatHydrateFinalized())
      } else {
        dispatch(setupChatHydrateAbort())
      }
    }
  },
)

export const selectSetupChatBusy = (state: RootState): boolean => state.setupChat.busy
export const selectSetupChatMessageQueue = (state: RootState): SetupChatQueuedMessage[] =>
  state.setupChat.messageQueue
export const selectSetupChatQueueDepth = (state: RootState): number => state.setupChat.messageQueue.length
export const selectSetupChatAutoMode = (state: RootState): boolean => state.setupChat.autoMode
export const selectSetupChatPendingChoice = (state: RootState): PendingChoice => state.setupChat.pendingChoice
export const selectSetupChatState = (state: RootState): ChatState => state.setupChat.chat
export const selectSetupChatHydrating = (state: RootState): boolean => state.setupChat.hydrating
export const selectSetupChatHydratedNovel = (state: RootState): string | null => state.setupChat.hydratedNovel
export const selectSetupChatHistoryLoadedNovel = (state: RootState): string | null =>
  state.setupChat.historyLoadedNovel
export const selectSetupChatHydrateEpoch = (state: RootState): number =>
  state.setupChat.hydrateEpoch

/** True when a queued user message can be POSTed (queue non-empty, agent idle, not hydrating). */
export const selectSetupChatCanDrainQueue = (state: RootState): boolean => {
  const sc = state.setupChat
  return sc.messageQueue.length > 0 && !sc.busy && !sc.hydrating
}
export default setupChatSlice.reducer
